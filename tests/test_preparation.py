"""Offline regressions; fake CLI outputs are not evidence of native slicing."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bambu', ROOT / 'skills/bambu-printing/scripts/bambu.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bambu test 中文 ')
        self.root = pathlib.Path(self.temp.name)
        self.path = self.root / 'centimetres.stl'
        trimesh.creation.box(extents=[2, 1, .7]).export(self.path)
        self.machine = {'name': 'machine', 'inherits': 'vendor machine', 'printer_model': 'Test',
                        'printer_settings_id': 'machine', 'nozzle_diameter': ['0.4'],
                        'printable_area': ['0x0', '100x0', '100x100', '0x100'], 'printable_height': '100'}
        self.process = {'name': 'process', 'inherits': 'vendor process', 'print_settings_id': 'process',
                        'print_sequence': 'by layer', 'brim_width': '0', 'brim_object_gap': '0'}
        self.filament = {'name': 'filament', 'inherits': 'vendor filament', 'filament_settings_id': ['filament']}
        self.manifest = {'objects': [{'path': str(self.path), 'units': 'cm', 'center_xy_mm': [30, 20], 'rotation_z_deg': 90}]}
        self.env = {'binary': '/fake/bambu', 'version': 'test', 'supports': dict.fromkeys(
            ['--load-settings', '--load-filaments', '--slice', '--export-3mf', '--arrange', '--orient', '--outputdir'], True)}
        self.config_dir = self.root / 'config'
        self.config_dir.mkdir()
        for kind, data in [('machine', self.machine), ('process', self.process), ('filament', self.filament)]:
            b.dump(data, self.config_dir / (kind + '.json'))

    def tearDown(self):
        self.temp.cleanup()

    def native_settings(self):
        return {**self.machine, **self.process, **self.filament, 'printer_settings_id': 'machine',
                'print_settings_id': 'process', 'curr_bed_type': 'Textured PEI Plate'}

    def fake_cli(self, command, **kwargs):
        source = pathlib.Path(command[-1])
        export_name = command[command.index('--export-3mf') + 1]
        self.assertEqual(export_name, 'sliced.3mf')
        target = pathlib.Path(kwargs['cwd']) / export_name
        self.assertEqual(kwargs['cwd'], str(target.parent))
        self.assertEqual(command[command.index('--arrange') + 1], '0')
        self.assertEqual(command[command.index('--orient') + 1], '0')
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, 'w') as output:
            for info in original.infolist():
                if not info.filename.startswith('Metadata/'):
                    output.writestr(info, original.read(info.filename))
            output.writestr('Metadata/project_settings.config', json.dumps(self.native_settings()))
            gcode = b'M83\nG1 X1 Y1 E0.5\nG1 X2 Y1 E0.3\n'
            output.writestr('Metadata/plate_1.gcode', gcode)
            output.writestr('Metadata/plate_1.gcode.md5', hashlib.md5(gcode).hexdigest())
            output.writestr('Metadata/model_settings.config', '<config><plate><metadata key="plater_id" value="1"/></plate></config>')
        b.dump({'return_code': 0}, target.parent / 'result.json')
        return subprocess.CompletedProcess(command, 0, '', '')

    def test_transformed_geometry_is_exact_staged_input(self):
        meshes, report = b.prepare_geometry(self.manifest, self.machine)
        staged = self.root / 'staged.3mf'
        b.stage_3mf(meshes, report, staged)
        actual = b.inspect_3mf(staged)
        b.compare_geometry(report['objects'], actual['build_objects'])
        np.testing.assert_allclose(actual['build_objects'][0]['dimensions_mm'], [10, 20, 7])
        np.testing.assert_allclose(actual['build_objects'][0]['bounds_mm'], [[25, 10, 0], [35, 30, 7]])

    def test_inch_conversion_and_unequal_placement(self):
        second = self.root / 'inches.stl'
        trimesh.creation.box(extents=[.5, .3, .2]).export(second)
        self.manifest['objects'].append({'path': str(second), 'units': 'inch', 'center_xy_mm': [65, 70], 'rotation_z_deg': 0})
        meshes, report = b.prepare_geometry(self.manifest, self.machine)
        staged = self.root / 'staged.3mf'
        b.stage_3mf(meshes, report, staged)
        actual = b.inspect_3mf(staged)
        b.compare_geometry(report['objects'], actual['build_objects'])
        np.testing.assert_allclose(actual['build_objects'][1]['dimensions_mm'], [12.7, 7.62, 5.08])

    def test_relative_paths_use_manifest_directory(self):
        self.manifest['objects'][0]['path'] = self.path.name
        b.dump(self.manifest, self.root / 'manifest.json')
        self.assertEqual(b.load_manifest(self.root / 'manifest.json')['objects'][0]['path'], str(self.path.resolve()))

    def test_empty_job_and_nonfinite_transform_rejected(self):
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            b.preflight({'objects': []}, self.machine)
        for key, value in [('rotation_z_deg', float('nan')), ('center_xy_mm', [20, float('inf')])]:
            job = copy.deepcopy(self.manifest)
            job['objects'][0][key] = value
            with self.assertRaises(ValueError):
                b.preflight(job, self.machine)

    def test_negative_individual_brim_is_rejected(self):
        self.manifest.update({'brim_width_mm': 5, 'brim_gap_mm': -1})
        with self.assertRaises(ValueError):
            b.preflight(self.manifest, self.machine)

    def test_single_object_sequence_is_valid(self):
        self.manifest['print_sequence'] = 'by object'
        self.assertEqual(b.preflight(self.manifest, self.machine)['status'], 'passed')

    def test_process_mismatch_rejected_before_subprocess(self):
        self.manifest['brim_width_mm'] = 3
        with patch.object(b.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'conflicts'):
                b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out.3mf', 'Textured PEI Plate')
            run.assert_not_called()

    def test_validation_before_publication_and_job_isolation(self):
        with patch.object(b.subprocess, 'run', side_effect=self.fake_cli):
            first = b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out.3mf', 'Textured PEI Plate')
            second = b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out2.3mf', 'Textured PEI Plate')
        self.assertEqual(first['status'], 'passed')
        self.assertEqual(first['native_gui_reopen'], 'not_run')
        self.assertNotEqual(first['diagnostics_dir'], second['diagnostics_dir'])
        self.assertTrue((self.root / 'out.report.json').is_file())
        self.assertFalse((self.root / 'result.json').exists())

    def test_final_bounds_change_does_not_publish(self):
        def move_output(command, **kwargs):
            result = self.fake_cli(command, **kwargs)
            target = pathlib.Path(kwargs['cwd']) / command[command.index('--export-3mf') + 1]
            with zipfile.ZipFile(target) as z:
                entries = {i.filename: z.read(i.filename) for i in z.infolist()}
            xml = ET.fromstring(entries['3D/3dmodel.model'])
            xml.find('m:build/m:item', b.NS).set('transform', '1 0 0 0 1 0 0 0 1 1 0 0')
            entries['3D/3dmodel.model'] = ET.tostring(xml)
            with zipfile.ZipFile(target, 'w') as z:
                for name, content in entries.items(): z.writestr(name, content)
            return result
        with patch.object(b.subprocess, 'run', side_effect=move_output):
            with self.assertRaisesRegex(RuntimeError, 'bounds mismatch'):
                b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out.3mf', 'Textured PEI Plate')
        self.assertFalse((self.root / 'out.3mf').exists())
        self.assertFalse((self.root / 'out.report.json').exists())
        self.assertEqual(len(list(self.root.glob('.out.job-*/failure.json'))), 1)

    def test_timeout_preserves_log_without_final_output(self):
        failure = subprocess.TimeoutExpired('bambu', 1, output=b'partial stdout', stderr=b'partial stderr')
        with patch.object(b.subprocess, 'run', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out.3mf', 'Textured PEI Plate', timeout=1)
        self.assertFalse((self.root / 'out.3mf').exists())
        self.assertIn('partial stderr', next(self.root.glob('.out.job-*/slicer.log')).read_text())

    def test_config_file_multi_extruder_rejected(self):
        self.machine['nozzle_diameter'] = ['0.4', '0.4']
        b.dump(self.machine, self.config_dir / 'machine.json')
        with patch.object(b.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'one physical'):
                b.slice_job(self.env, self.config_dir, self.manifest, self.root / 'out.3mf', 'Textured PEI Plate')
            run.assert_not_called()

    def test_positional_models_no_longer_launch(self):
        diagnostic = io.StringIO()
        with patch.object(b.sys, 'argv', ['bambu.py', 'slice', '--config-dir', 'c', '--bed', 'b', '--output', 'o', 'raw.stl']), patch.object(b, 'discover') as discover, contextlib.redirect_stderr(diagnostic):
            with self.assertRaises(SystemExit): b.main()
            discover.assert_not_called()
        self.assertIn('Migrate to: slice --manifest', diagnostic.getvalue())
        self.assertIn('center_xy_mm', diagnostic.getvalue())

    def test_slice_help_and_equals_manifest_remain_valid(self):
        with patch.object(b.sys, 'argv', ['bambu.py', 'slice', '--help']), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:b.main()
            self.assertEqual(result.exception.code, 0)
        argv = ['bambu.py', 'slice', '--manifest=job.json', '--config-dir=config', '--bed=plate', '--output=out.3mf']
        with patch.object(b.sys, 'argv', argv), patch.object(b, 'discover', return_value=self.env), patch.object(b, 'slice_job', return_value={}) as run, contextlib.redirect_stdout(io.StringIO()):
            b.main()
            self.assertEqual(run.call_args.args[2], 'job.json')

    def test_config_file_postprocess_rejected_in_every_group(self):
        for group in ('machine', 'process', 'filament'):
            settings = {'machine': self.machine, 'process': self.process, 'filament': self.filament}
            settings = copy.deepcopy(settings)
            settings[group]['post_process'] = ['do-not-run']
            with self.assertRaisesRegex(ValueError, 'post-process'):
                b.validate_effective_configs(settings)

    def test_reslice_preserves_local_override_and_embedded_settings(self):
        meshes, report = b.prepare_geometry(self.manifest, self.machine)
        source = self.root / 'native.3mf'
        b.stage_3mf(meshes, report, source)
        settings = self.native_settings()
        local = '<config><object id="1"><metadata key="name" value="prepared_0001"/><metadata face_count="12"/><metadata key="wall_loops" value="5"/><part id="1" subtype="normal_part"><metadata key="sparse_infill_density" value="22%"/></part></object><plate><metadata key="plater_id" value="1"/></plate></config>'
        with zipfile.ZipFile(source, 'a') as z:
            z.writestr('Metadata/project_settings.config', json.dumps(settings))
            z.writestr('Metadata/model_settings.config', local)
        def native_copy(command, **kwargs):
            self.assertNotIn('--load-settings', command)
            self.assertEqual(command[command.index('--load-filaments') + 1], '""')
            self.assertNotIn('--no-check', command)
            target = pathlib.Path(kwargs['cwd']) / command[command.index('--export-3mf') + 1]
            with zipfile.ZipFile(command[-1]) as src, zipfile.ZipFile(target, 'w') as out:
                for info in src.infolist():out.writestr(info, src.read(info.filename))
                out.writestr('Metadata/plate_1.gcode', 'M83\nG1 X1 Y1 E1\n')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch.object(b.subprocess, 'run', side_effect=native_copy):
            result = b.reslice_job(self.env, source, self.root / 'resliced.3mf')
        self.assertEqual(result['local_settings'][0]['settings']['wall_loops'], '5')
        self.assertEqual(b.digest(source), b.inspect_3mf(source)['sha256'])

    def test_reslice_multiple_slots_rejected(self):
        report = {'has_model': True, 'project_settings': self.native_settings(), 'model_plates': [{}], 'build_objects': []}
        report['project_settings']['filament_settings_id'] = ['PLA', 'PETG']
        with self.assertRaisesRegex(ValueError, 'one filament'):
            b.native_project_capability(report)

    def test_reslice_unverified_editing_members_and_painting_rejected(self):
        report = {'has_model': True, 'project_settings': self.native_settings(), 'model_plates': [{}],
                  'build_objects': [{'name': 'one', 'printable': True}]}
        report['unsupported_editing_members'] = ['Metadata/layer_heights_profile.txt']
        with self.assertRaisesRegex(ValueError, 'editing/painting'):
            b.native_project_capability(report)
        report['unsupported_editing_members'] = []
        report['build_objects'][0]['unsupported_geometry_features'] = ['triangle_attribute:paint_supports']
        with self.assertRaisesRegex(ValueError, 'editing/painting'):
            b.native_project_capability(report)

    def test_inspector_inventories_painting_and_active_editing_payload(self):
        meshes, report = b.prepare_geometry(self.manifest, self.machine)
        path = self.root / 'advanced.3mf'
        b.stage_3mf(meshes, report, path)
        with zipfile.ZipFile(path) as z:entries = {name: z.read(name) for name in z.namelist()}
        model = ET.fromstring(entries['3D/3dmodel.model'])
        model.find('m:resources/m:object/m:mesh/m:triangles/m:triangle', b.NS).set('paint_supports', '1')
        entries['3D/3dmodel.model'] = ET.tostring(model)
        entries['Metadata/layer_heights_profile.txt'] = b'object_id=1|0.2;0.1'
        entries['Metadata/cut_information.xml'] = b'<objects><object id="1"><cut_id id="0" check_sum="1" connectors_cnt="0"/></object></objects>'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in entries.items():z.writestr(name, data)
        inspected = b.inspect_3mf(path)
        self.assertEqual(inspected['unsupported_editing_members'], ['Metadata/layer_heights_profile.txt'])
        self.assertIn('triangle_attribute:paint_supports', inspected['build_objects'][0]['unsupported_geometry_features'])


class InspectionTest(unittest.TestCase):
    def inspect_gcode(self, text):
        return b.inspect_gcode(io.BytesIO(text.encode()))

    def test_extrusion_requires_positive_E_and_XY_motion(self):
        for text in ['', '; G1 X1 Y1 E1\n', 'G1 X1 Y1\n', 'M83\nG1 E1\n', 'M83\nG1 X1 E-1\n']:
            self.assertEqual(self.inspect_gcode(text)['extrusion_moves'], 0)
        text = 'M82\nG92 E100\nG1 X1 E101\nG1 X2 E100\nM83\nG1 X3 E0.5\n'
        self.assertEqual(self.inspect_gcode(text)['extrusion_moves'], 2)

    def test_empty_gcode_does_not_prove_toolpaths(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / 'empty.3mf'
            with zipfile.ZipFile(path, 'w') as z:z.writestr('Metadata/plate_1.gcode', '')
            self.assertFalse(b.inspect_3mf(path)['has_toolpaths'])

    def test_md5_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / 'bad.3mf'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('Metadata/plate_1.gcode', 'M83\nG1 X1 E1\n')
                z.writestr('Metadata/plate_1.gcode.md5', '0' * 32)
            with self.assertRaisesRegex(ValueError, 'MD5 mismatch'):b.inspect_3mf(path)

    def test_vertices_without_faces_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / 'no-face.3mf'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('3D/3dmodel.model', f'<model xmlns="{b.CORE}"><resources><object id="1"><mesh><vertices><vertex x="1" y="2" z="3"/></vertices></mesh></object></resources><build><item objectid="1"/></build></model>')
            with self.assertRaisesRegex(ValueError, 'triangle faces'):b.inspect_3mf(path)

    def test_tolerance_zero_relative_error(self):
        expected = [{'name': 'part', 'bounds_mm': [[1, 2, 3], [11, 12, 13]], 'dimensions_mm': [10, 10, 10]}]
        actual = copy.deepcopy(expected)
        actual[0]['bounds_mm'][0][0] += .009
        b.compare_geometry(expected, actual)
        actual[0]['bounds_mm'][0][0] += .002
        with self.assertRaisesRegex(ValueError, 'bounds mismatch'):b.compare_geometry(expected, actual)

    def test_changed_local_settings_rejected_by_comparison(self):
        with self.assertRaisesRegex(ValueError, 'setting changed'):
            b.compare_project_settings({'wall_loops': '4'}, {'wall_loops': '2'})

    def test_explicit_invalid_paths_never_fall_back(self):
        with patch.object(b.subprocess, 'run') as run, patch.object(b.shutil, 'which', return_value='/installed/bambu'):
            with self.assertRaisesRegex(FileNotFoundError, 'Explicit'):
                b.discover('/nonexistent/chosen-bambu')
            run.assert_not_called()
        with tempfile.NamedTemporaryFile() as binary:
            with patch.object(b.subprocess, 'run') as run:
                with self.assertRaisesRegex(FileNotFoundError, 'Explicit BBL'):
                    b.discover(binary.name, '/nonexistent/profiles')
                run.assert_not_called()

    def test_environment_probe_is_isolated_and_uses_utf8(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            binary = root / 'bambu'
            binary.touch()
            for kind in ('machine', 'process', 'filament'):(root / 'profiles' / kind).mkdir(parents=True)
            def help_probe(argv, **kwargs):
                self.assertEqual(kwargs['encoding'], 'utf-8')
                self.assertEqual(kwargs['errors'], 'replace')
                self.assertNotEqual(pathlib.Path(kwargs['cwd']), pathlib.Path.cwd())
                (pathlib.Path(kwargs['cwd']) / 'result.json').write_text('{}')
                return subprocess.CompletedProcess(argv, 0, 'BambuStudio-02.08.04.57\n--slice --export-3mf', '')
            with patch.object(b.subprocess, 'run', side_effect=help_probe), patch.object(b.platform, 'platform', return_value='test-platform'):
                report = b.discover(str(binary), str(root / 'profiles'))
            self.assertEqual(report['version'], '02.08.04.57')
            self.assertFalse((root / 'result.json').exists())

    def test_unknown_native_errors_are_not_success(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            b.classify_messages('[error] skipped object', '02.08.04.57', {})
        messages, known = b.classify_messages('[error] Invalid T command (T65535)', '02.08.04.57', {'machine_end_gcode': 'T65535'})
        self.assertEqual(messages, known)


if __name__ == '__main__': unittest.main()
