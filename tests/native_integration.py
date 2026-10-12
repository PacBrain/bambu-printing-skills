#!/usr/bin/env python3
"""Opt-in native tests using synthetic geometry only. Never sends jobs to a printer.

Run explicitly; unittest discovery does not execute this module:
  python tests/native_integration.py run --output-dir /tmp/bambu-native-unique
Native GUI reopening remains a separate, manual acceptance step.
"""
import argparse
import importlib.util
import json
import pathlib
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bambu', ROOT / 'skills/bambu-printing/scripts/bambu.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def fixture(directory, env):
    import trimesh
    directory = pathlib.Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    trimesh.creation.box(extents=[2, 1, .7]).export(directory / 'centimetres.stl')
    trimesh.creation.box(extents=[.5, .3, .2]).export(directory / 'inches.stl')
    b.dump({'objects': [
        {'path': 'centimetres.stl', 'units': 'cm', 'center_xy_mm': [80, 95], 'rotation_z_deg': 90},
        {'path': 'inches.stl', 'units': 'inch', 'center_xy_mm': [225, 180], 'rotation_z_deg': 0},
    ]}, directory / 'manifest.json')
    data, trace = b.configs(env, 'Bambu Lab H2S 0.4 nozzle', '0.20mm Standard @BBL H2S',
                          'Bambu PLA Basic @BBL H2S', {'process': {'wall_loops': '3', 'sparse_infill_density': '15%', 'brim_type': 'no_brim'}})
    for kind, settings in data.items():b.dump(settings, directory / 'configs' / (kind + '.json'))
    b.dump({'software': env, 'profiles': trace}, directory / 'environment.json')
    return directory


def local_override(source, output):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as dst:
        found = False
        for info in src.infolist():
            # Force freshly produced paths; avoid presenting old cached G-code as new evidence.
            if info.filename.endswith(('.gcode', '.gcode.md5')):continue
            content = src.read(info.filename)
            if info.filename.endswith('model_settings.config'):
                root = ET.fromstring(content)
                obj = root.find('object')
                if obj is None:raise ValueError('Native fixture has no object metadata')
                node = next((e for e in obj.findall('metadata') if e.get('key') == 'wall_loops'), None)
                if node is None:node = ET.SubElement(obj, 'metadata', {'key': 'wall_loops'})
                node.set('value', '5')
                content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                found = True
            dst.writestr(info, content)
        if not found:raise ValueError('Native fixture has no model settings')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary')
    parser.add_argument('--profiles')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'run'):
        q = commands.add_parser(command)
        q.add_argument('--output-dir', required=True)
    q = commands.add_parser('reslice')
    q.add_argument('--project', required=True)
    q.add_argument('--output', required=True)
    args = parser.parse_args()
    env = b.discover(args.binary, args.profiles)
    if args.command == 'reslice':
        report = b.reslice_job(env, args.project, args.output)
        b.dump({'reslice': report['status'], 'output': str(pathlib.Path(args.output).resolve()), 'gui_reopen': 'not_run', 'physical_print': 'not_run'})
        return
    directory = fixture(args.output_dir, env)
    if args.command == 'prepare':
        b.dump({'fixture': str(directory), 'native_slice': 'not_run'})
        return
    phase = 'manifest_slice'
    try:
        first = b.slice_job(env, directory / 'configs', directory / 'manifest.json', directory / 'manifest.3mf', 'Textured PEI Plate')
        phase = 'local_override_reslice'
        local_override(directory / 'manifest.3mf', directory / 'local-override.3mf')
        second = b.reslice_job(env, directory / 'local-override.3mf', directory / 'resliced.3mf')
        if not any(item['settings'].get('wall_loops') == '5' for item in second['local_settings']):
            raise ValueError('Local wall_loops=5 did not survive native reslicing')
        b.dump({'status': 'passed', 'manifest_slice': first['status'], 'local_override_reslice': second['status'],
                'outputs': [str(directory / 'manifest.3mf'), str(directory / 'resliced.3mf')],
                'native_gui_reopen': 'not_run', 'physical_print': 'not_run'}, directory / 'integration-status.json')
        print((directory / 'integration-status.json').read_text(encoding='utf-8'))
    except Exception as exc:
        b.dump({'status': 'failed', 'phase': phase, 'error': str(exc), 'physical_print': 'not_run'}, directory / 'integration-status.json')
        raise


if __name__ == '__main__':
    main()
