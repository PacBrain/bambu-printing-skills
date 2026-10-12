#!/usr/bin/env python3
"""Local, offline Bambu Studio preparation; never connects to or starts a printer."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import pathlib
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

Path = pathlib.Path
CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
PRODUCTION = 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'m': CORE}
BOUNDS_TOLERANCE_MM = 0.01
UNITS = {'micron': .001, 'millimeter': 1, 'centimeter': 10, 'meter': 1000, 'inch': 25.4, 'foot': 304.8}
# This leaf was checked against the installed 02.08.04.57 H2S profile. Other
# parameter includes need native-default-aware merging, not a blind dict update.
VERIFIED_PARAMETER_INCLUDES = {
    ('filament', 'fdm_filament_template_direct_dual_e3d'):
        '99cc6625639cc43480ac064b54986fc669697759be50dbae0cdcd5ad9adce9e0',
}
PROFILE_METADATA = {'type', 'name', 'from', 'instantiation', 'setting_id', 'description'}
PROTECTED_KEYS = {
    'name', 'type', 'from', 'instantiation', 'inherits', 'include',
    'printer_settings_id', 'print_settings_id', 'filament_settings_id',
    'different_settings_to_system', 'printer_model', 'printer_variant',
    'nozzle_diameter', 'nozzle_volume_type', 'default_nozzle_volume_type',
    'printable_area', 'printable_height', 'bed_exclude_area', 'wrapping_exclude_area',
    'extruder_type', 'physical_extruder_map', 'filament_map', 'filament_volume_map',
    'filament_nozzle_map', 'filament_self_index', 'filament_type', 'filament_id',
}
RUNTIME_KEYS = {'process': {'brim_type', 'only_one_wall_first_layer', 'timelapse_type', 'top_one_wall_type'}}
UNVERIFIED_EDITING_MEMBERS = {
    'layer_heights_profile.txt', 'layer_config_ranges.xml', 'brim_ear_points.txt',
    'custom_gcode_per_layer.xml', 'cut_information.xml', 'assembly_tree.json',
    'assembly_step.json', 'assembly_model.json',
}
SUPPORTED_PART_TYPES = {'normal_part', 'negative_part', 'modifier_part', 'support_enforcer', 'support_blocker'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(f.read()).hexdigest()


def dump(value, target=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if target:
        p = Path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    else:
        print(text)
    return value


def read_json(path):
    result = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(result, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return result


def finite(value, label, minimum=None):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a finite number')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a finite number') from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(f'{label} must be finite and >= {minimum}')
    return number


def discover(binary=None, profiles=None):
    selected = binary or os.environ.get('BAMBU_STUDIO_BIN')
    if selected:
        exe = Path(selected).expanduser().resolve()
        if not exe.is_file():
            raise FileNotFoundError('Explicit Bambu Studio binary does not exist: ' + str(exe))
    else:
        candidates = [shutil.which('bambu-studio'), shutil.which('BambuStudio')]
        if sys.platform == 'darwin':
            candidates += ['/Applications/BambuStudio.app/Contents/MacOS/BambuStudio',
                           str(Path.home() / 'Applications/BambuStudio.app/Contents/MacOS/BambuStudio')]
        if sys.platform == 'win32':
            candidates += [str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Bambu Studio/bambu-studio.exe')]
        exe = next((Path(p).resolve() for p in candidates if p and Path(p).is_file()), None)
        if exe is None:
            raise FileNotFoundError('Bambu Studio not found; supply --binary or BAMBU_STUDIO_BIN')
    selected_profiles = profiles or os.environ.get('BAMBU_PROFILES')
    if selected_profiles:
        root = Path(selected_profiles).expanduser().resolve()
        if not all((root / kind).is_dir() for kind in ('machine', 'process', 'filament')):
            raise FileNotFoundError('Explicit BBL profiles directory is invalid: ' + str(root))
    else:
        roots = [exe.parent.parent / 'Resources/profiles/BBL', exe.parent.parent / 'resources/profiles/BBL',
                 exe.parent / 'resources/profiles/BBL', exe.parent.parent / 'share/BambuStudio/profiles/BBL',
                 Path('/usr/share/BambuStudio/profiles/BBL'), Path('/usr/local/share/BambuStudio/profiles/BBL')]
        root = next((p for p in roots if all((p / k).is_dir() for k in ('machine', 'process', 'filament'))), None)
        if root is None:
            raise FileNotFoundError('Official BBL profiles not found; supply --profiles (AppImage/Flatpak may need an exposed resource directory)')
    # Even --help can write native result.json; never let an environment probe
    # write diagnostic files into the caller's project directory.
    with tempfile.TemporaryDirectory(prefix='bambu-env-') as probe:
        run = subprocess.run([str(exe), '--help'], cwd=probe, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    help_text = run.stdout + '\n' + run.stderr
    if run.returncode:
        raise RuntimeError(help_text)
    match = re.search(r'BambuStudio[- ]([0-9][0-9.]+)', help_text)
    return {'binary': str(exe), 'profiles': str(root), 'platform': platform.platform(),
            'version': match.group(1) if match else 'unknown',
            'supports': {x: x in help_text for x in ['--load-settings', '--load-filaments', '--slice', '--export-3mf', '--arrange', '--orient', '--outputdir']}}


class Profiles:
    """Resolve parent chains and bounded includes, preserving source provenance."""

    def __init__(self, root):
        self.root = Path(root)
        self.maps = {}
        self.trace = []
        for kind in ('machine', 'process', 'filament'):
            self.maps[kind] = {}
            for p in (self.root / kind).rglob('*.json'):
                d = read_json(p)
                for name in (p.stem, d.get('name')):
                    if name:
                        old = self.maps[kind].get(name)
                        if old and old != p:
                            raise ValueError('Duplicate profile name: ' + name)
                        self.maps[kind][name] = p

    def _read(self, kind, name):
        p = self.maps.get(kind, {}).get(name)
        if p is None:
            raise ValueError(f'Missing {kind} profile: {name}')
        d = read_json(p)
        record = {'kind': kind, 'name': name, 'sha256': digest(p)}
        if record not in self.trace:
            self.trace.append(record)
        return d

    def include(self, kind, name, stack):
        if (kind, name) in stack:
            raise ValueError('Profile inheritance/include cycle')
        d = self._read(kind, name)
        if d.get('inherits') or d.get('include'):
            raise ValueError(f'Unsupported inherited/nested include: {name}; export full settings from native Studio')
        values = {k: v for k, v in d.items() if k not in PROFILE_METADATA | {'inherits', 'include'}}
        pure_gcode = bool(values) and all(k.endswith('_gcode') and isinstance(v, str) and v.strip() for k, v in values.items())
        known = VERIFIED_PARAMETER_INCLUDES.get((kind, name))
        verified = known and hashlib.sha256(canonical(d).encode()).hexdigest() == known
        if not (pure_gcode or verified):
            raise ValueError(f'Unsupported parameter include: {name}; native-default-aware merging is not verified; use a native Studio full export')
        return values

    def resolve(self, kind, name, stack=()):
        token = (kind, name)
        if token in stack:
            raise ValueError('Profile inheritance/include cycle: ' + repr(stack + (token,)))
        d = self._read(kind, name)
        result = {}
        if d.get('inherits'):
            result.update(self.resolve(kind, d['inherits'], stack + (token,)))
        includes = d.get('include', [])
        if isinstance(includes, str):
            includes = [includes]
        if not isinstance(includes, list) or not all(isinstance(x, str) for x in includes):
            raise ValueError('Profile include must contain names')
        for child in includes:
            result.update(self.include(kind, child, stack + (token,)))
        result.update({k: v for k, v in d.items() if k not in ('inherits', 'include')})
        return result


def supported_hardware(settings, require_material=False):
    nozzles = settings.get('nozzle_diameter')
    if not isinstance(nozzles, list) or len(nozzles) != 1 or finite(nozzles[0], 'nozzle diameter', 0) <= 0:
        raise ValueError('Automation requires one physical extruder with a positive nozzle diameter')
    for key, allowed in [('nozzle_volume_type', {'0', 'Standard', 'standard'}),
                         ('extruder_type', {'0', 'Direct Drive', 'direct_drive', 'DirectDrive'})]:
        value = settings.get(key)
        if value is not None and (not isinstance(value, list) or len(value) != 1 or str(value[0]) not in allowed):
            raise ValueError(f'Unsupported {key}; automation supports standard direct-drive hotends only')
    defaults = settings.get('default_nozzle_volume_type')
    if defaults is not None and (not isinstance(defaults, list) or len(defaults) != 1 or str(defaults[0]) not in {'0', 'Standard', 'standard'}):
        raise ValueError('Unsupported default nozzle volume type')
    # In native Studio absent nozzle_volume_type/extruder_type use the standard
    # direct-drive defaults. Variant lists enumerate available, not selected, hardware.
    if require_material:
        slots = settings.get('filament_settings_id')
        if not isinstance(slots, list) or len(slots) != 1 or not slots[0]:
            raise ValueError('Automation requires exactly one filament slot; use native Studio for multiple materials')
        for key in ('filament_map', 'filament_volume_map'):
            values = settings.get(key)
            if values is not None and (not isinstance(values, list) or len(values) != 1):
                raise ValueError('Unsupported filament mapping: ' + key)
        if settings.get('filament_volume_map') and str(settings['filament_volume_map'][0]) not in {'0', 'Standard', 'standard'}:
            raise ValueError('Unsupported high-flow filament mapping')
        if settings.get('filament_map') and str(settings['filament_map'][0]) != '1':
            raise ValueError('Unsupported extruder mapping')


def validate_effective_configs(data):
    machine = data['machine']
    supported_hardware(machine)
    variants = machine.get('printer_extruder_variant', [])
    if variants and 'Direct Drive Standard' not in variants:
        raise ValueError('Selected printer has no standard direct-drive variant')
    identity = machine.get('inherits') or machine.get('name')
    for kind in ('process', 'filament'):
        allowed = data[kind].get('compatible_printers', [])
        if allowed and identity not in allowed:
            raise ValueError(f'{kind} incompatible with {identity}')
    for kind, d in data.items():
        if not isinstance(d, dict):
            raise ValueError(f'{kind} settings must be an object')
        if d.get('post_process'):
            raise ValueError('Executable post-process commands are unsupported in all configuration groups')
        for key in ('layer_height', 'initial_layer_print_height'):
            if key in d and finite(d[key], key, 0) <= 0:
                raise ValueError(key + ' must be positive')
        for key in ('wall_loops', 'brim_width', 'brim_object_gap'):
            if key in d:
                finite(d[key], key, 0)
        if 'sparse_infill_density' in d:
            density = finite(str(d['sparse_infill_density']).rstrip('%'), 'sparse_infill_density', 0)
            if density > 100:
                raise ValueError('sparse_infill_density must be <= 100%')
        if 'print_sequence' in d and d['print_sequence'] not in ('by layer', 'by object'):
            raise ValueError('Unknown print sequence')
        if 'top_one_wall_type' in d and d['top_one_wall_type'] not in ('not apply', 'all top', 'topmost'):
            raise ValueError('Invalid top_one_wall_type')
        for key in ('support_filament', 'support_interface_filament', 'sparse_infill_filament', 'solid_infill_filament', 'wall_filament'):
            if key in d and str(d[key]) not in ('0', '1'):
                raise ValueError('Only the first filament slot is supported: ' + key)
    slots = data['filament'].get('filament_settings_id')
    if slots is not None and (not isinstance(slots, list) or len(slots) != 1):
        raise ValueError('Only one material is supported')


def configs(env, machine, process, filament, overrides=None, variant='Direct Drive Standard'):
    if variant != 'Direct Drive Standard':
        raise ValueError('Automated non-standard hotends are not validated; prepare them in native Studio')
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError('Overrides must be machine/process/filament objects')
    lib = Profiles(env['profiles'])
    resolved = {k: lib.resolve(k, n) for k, n in [('machine', machine), ('process', process), ('filament', filament)]}
    for kind, changes in (overrides or {}).items():
        if kind not in resolved or not isinstance(changes, dict):
            raise ValueError('Overrides must be machine/process/filament objects')
        for key, value in changes.items():
            if 'gcode' in key.lower() or key == 'post_process':
                raise ValueError('This helper does not override G-code or post-process commands')
            if key == 'only_one_wall_top':
                raise ValueError('Deprecated only_one_wall_top; use top_one_wall_type')
            if key in PROTECTED_KEYS or 'extruder' in key or key.startswith('compatible_'):
                raise ValueError('Protected hardware/profile identity key: ' + key)
            if key not in resolved[kind] and key not in RUNTIME_KEYS.get(kind, set()):
                raise ValueError(f'Unknown {kind} key: {key}')
            old = resolved[kind].get(key)
            if old is not None and isinstance(old, list) != isinstance(value, list):
                raise ValueError('Override must retain scalar/array shape: ' + key)
            resolved[kind][key] = value
    validate_effective_configs(resolved)
    for kind, d in resolved.items():
        base = d['name']
        d.update({'from': 'User', 'instantiation': 'true', 'inherits': base, 'name': base + ' - Prepared'})
        key = {'machine': 'printer_settings_id', 'process': 'print_settings_id', 'filament': 'filament_settings_id'}[kind]
        d[key] = [d['name']] if kind == 'filament' else d['name']
        d['different_settings_to_system'] = [';'.join(sorted((overrides or {}).get(kind, {})))]
    validate_effective_configs(resolved)
    return resolved, lib.trace


def write_configs(env, args):
    overrides = read_json(args.overrides) if args.overrides else None
    data, trace = configs(env, args.machine, args.process, args.filament, overrides, args.variant)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    for kind, d in data.items():
        dump(d, out / (kind + '.json'))
    dump({'software': env['version'], 'variant': args.variant, 'sources': trace}, out / 'provenance.json')
    return {k: str(out / (k + '.json')) for k in data}


def mesh_info(path, units):
    import numpy as np
    import trimesh
    if units not in ('mm', 'cm', 'm', 'inch'):
        raise ValueError('Explicit source units are required (mm/cm/m/inch)')
    path = Path(path)
    if path.suffix.lower() != '.stl':
        raise ValueError('Manifest preparation accepts one STL per object; native 3MF uses reslice')
    content = path.read_bytes()
    mesh = trimesh.load_mesh(io.BytesIO(content), file_type='stl', process=True)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError('Empty/non-finite mesh or unsupported scene')
    mesh.apply_scale({'mm': 1, 'cm': 10, 'm': 1000, 'inch': 25.4}[units])
    counts = np.bincount(mesh.edges_unique_inverse)
    report = {'name': path.name, 'source_sha256': hashlib.sha256(content).hexdigest(),
              'units': 'mm', 'source_units': units, 'dimensions_mm': mesh.extents.tolist(), 'bounds_mm': mesh.bounds.tolist(),
              'vertices': len(mesh.vertices), 'triangles': len(mesh.faces), 'watertight': bool(mesh.is_watertight),
              'winding_consistent': bool(mesh.is_winding_consistent), 'positive_volume': bool(mesh.volume > 0),
              'volume_mm3': float(mesh.volume), 'nonmanifold_edges': int(sum(counts > 2)),
              'self_intersections': 'not_run', 'minimum_wall_thickness': 'not_run'}
    if not all(report[k] for k in ('watertight', 'winding_consistent', 'positive_volume')) or report['nonmanifold_edges']:
        raise ValueError('Mesh is not a consistently oriented closed volume: ' + json.dumps(report))
    return mesh, report


def load_manifest(path):
    path = Path(path).resolve()
    manifest = read_json(path)
    for obj in manifest.get('objects', []):
        if not isinstance(obj, dict) or not isinstance(obj.get('path'), str):
            raise ValueError('Every manifest object requires a file path')
        source = Path(obj['path']).expanduser()
        obj['path'] = str((path.parent / source).resolve() if not source.is_absolute() else source.resolve())
    return manifest


def effective_manifest(manifest, process):
    result = copy.deepcopy(manifest)
    settings = {'print_sequence': process.get('print_sequence', 'by layer'),
                'brim_width_mm': finite(process.get('brim_width', 0), 'brim_width', 0),
                'brim_gap_mm': finite(process.get('brim_object_gap', 0), 'brim_object_gap', 0)}
    # Auto brim can use less than the configured width. Keep the full configured
    # width as the conservative envelope; disabled brim adds no envelope.
    if process.get('brim_type') == 'no_brim':
        settings['brim_width_mm'] = 0.0
        settings['brim_gap_mm'] = 0.0
    for key, value in settings.items():
        if key in result:
            actual = result[key] if key == 'print_sequence' else finite(result[key], key, 0)
            if actual != value:
                raise ValueError(f'Manifest {key} conflicts with effective process settings ({value!r})')
        result[key] = value
    return result


def prepare_geometry(manifest, machine):
    """Return one set of transformed meshes for BOTH preflight and staged input."""
    import numpy as np
    import trimesh
    from shapely.geometry import Polygon, box

    def polygon(points, label):
        values = []
        for p in points:
            pair = p.split('x') if isinstance(p, str) else p
            if len(pair) != 2:
                raise ValueError('Invalid polygon point in ' + label)
            values.append(tuple(finite(v, label) for v in pair))
        shape = Polygon(values)
        if not shape.is_valid or shape.area <= 0:
            raise ValueError('Invalid polygon: ' + label)
        return shape

    if not isinstance(manifest.get('objects'), list) or not manifest['objects']:
        raise ValueError('Manifest objects must be a nonempty list')
    seq = manifest.get('print_sequence', 'by layer')
    if seq not in ('by layer', 'by object'):
        raise ValueError('Unknown print sequence')
    bed = polygon(machine['printable_area'], 'printable_area')
    max_height = finite(machine['printable_height'], 'printable_height', 0)
    excludes = []
    for key in ('bed_exclude_area', 'wrapping_exclude_area'):
        if machine.get(key):
            excludes.append((key, polygon(machine[key], key)))
    for points in manifest.get('additional_exclude_areas', []):
        excludes.append(('job_exclusion', polygon(points, 'job_exclusion')))
    clearance = finite(manifest.get('brim_width_mm', 0), 'brim width', 0) + finite(manifest.get('brim_gap_mm', 0), 'brim gap', 0)
    footprints, objects, meshes, failures = [], [], [], []
    for index, obj in enumerate(manifest['objects']):
        mesh, info = mesh_info(obj['path'], obj.get('units'))
        mesh.vertices -= np.array([*mesh.bounds.mean(axis=0)[:2], mesh.bounds[0, 2]])
        angle = finite(obj.get('rotation_z_deg', 0), 'rotation_z_deg')
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(angle), [0, 0, 1]))
        center = obj.get('center_xy_mm')
        if not isinstance(center, list) or len(center) != 2:
            raise ValueError('center_xy_mm must contain two finite numbers')
        mesh.apply_translation([finite(center[0], 'center X'), finite(center[1], 'center Y'), 0])
        a, b = mesh.bounds
        footprint = box(a[0], a[1], b[0], b[1]).buffer(clearance, join_style=2)
        if not bed.covers(footprint):
            failures.append(info['name'] + ': outside printable area including brim')
        for label, zone in excludes:
            if footprint.intersects(zone):
                failures.append(info['name'] + ': intersects ' + label)
        if b[2] > max_height:
            failures.append(info['name'] + ': exceeds printable height')
        if any(footprint.intersects(previous) for previous in footprints):
            failures.append(info['name'] + ': overlapping model/brim footprint')
        identity = f'prepared_{index + 1:04d}'
        info.update({'identity': identity, 'placed_bounds_mm': [a.tolist(), b.tolist()], 'placed_dimensions_mm': mesh.extents.tolist()})
        footprints.append(footprint)
        objects.append(info)
        meshes.append(mesh)
    if seq == 'by object' and len(objects) > 1:
        radius = finite(machine.get('extruder_clearance_radius', 0), 'extruder clearance radius', 0)
        height = finite(machine.get('extruder_clearance_height_to_rod', 0), 'extruder clearance height', 0)
        if radius <= 0 or height <= 0:
            failures.append('Sequential-print head clearance unavailable')
        for i, obj in enumerate(objects[:-1]):
            if obj['placed_dimensions_mm'][2] > height:
                failures.append(obj['name'] + ': exceeds conservative sequential head clearance')
            if any(footprints[i].buffer(radius).intersects(other) for other in footprints[i + 1:]):
                failures.append(obj['name'] + ': sequential head collision envelope overlaps')
    report = {'status': 'failed' if failures else 'passed', 'objects': objects, 'errors': failures,
              'print_sequence': seq, 'brim_clearance_mm': clearance,
              'scope': 'Conservative static bounds only; final slicer paths and physical printing require separate checks.'}
    return meshes, report


def preflight(manifest, machine, process=None):
    return prepare_geometry(effective_manifest(manifest, process) if process is not None else manifest, machine)[1]


def stage_3mf(meshes, preflight_report, target):
    """Write a core 3MF with explicit millimetre coordinates and stable names."""
    ET.register_namespace('', CORE)
    model = ET.Element(f'{{{CORE}}}model', {'unit': 'millimeter', '{http://www.w3.org/XML/1998/namespace}lang': 'en-US'})
    resources = ET.SubElement(model, f'{{{CORE}}}resources')
    build = ET.SubElement(model, f'{{{CORE}}}build')
    for index, (mesh, info) in enumerate(zip(meshes, preflight_report['objects']), 1):
        obj = ET.SubElement(resources, f'{{{CORE}}}object', {'id': str(index), 'type': 'model', 'name': info['identity']})
        body = ET.SubElement(obj, f'{{{CORE}}}mesh')
        vertices = ET.SubElement(body, f'{{{CORE}}}vertices')
        for vertex in mesh.vertices:
            ET.SubElement(vertices, f'{{{CORE}}}vertex', dict(zip(('x', 'y', 'z'), (format(float(v), '.12g') for v in vertex))))
        triangles = ET.SubElement(body, f'{{{CORE}}}triangles')
        for face in mesh.faces:
            ET.SubElement(triangles, f'{{{CORE}}}triangle', dict(zip(('v1', 'v2', 'v3'), map(str, face))))
        ET.SubElement(build, f'{{{CORE}}}item', {'objectid': str(index)})
    content_types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    relationships = f'<Relationships xmlns="{REL}"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', relationships)
        z.writestr('3D/3dmodel.model', ET.tostring(model, encoding='utf-8', xml_declaration=True))


def checked_archive(z):
    names = z.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate archive entries')
    if len(names) > 10000 or sum(i.file_size for i in z.infolist()) > 4 * 1024 ** 3:
        raise ValueError('3MF exceeds inspection resource limits')
    for name in names:
        if name.startswith('/') or '\\' in name or '..' in name.split('/'):
            raise ValueError('Invalid archive member path: ' + name)
    return names


def archive_xml(z, name):
    if z.getinfo(name).file_size > 256 * 1024 ** 2:
        raise ValueError('XML exceeds inspection limit: ' + name)
    raw = z.read(name)
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('DTD/entity declarations are unsupported in 3MF')
    return ET.fromstring(raw)


def main_model_path(z):
    if '_rels/.rels' in z.namelist():
        root = archive_xml(z, '_rels/.rels')
        models = [e.get('Target') for e in root if e.get('Type', '').endswith('/3dmodel') and e.get('TargetMode', 'Internal') == 'Internal']
        if len(models) != 1:
            raise ValueError('3MF must have one internal primary model relationship')
        return models[0].lstrip('/')
    # Existing Bambu sliced-plate stubs and historical synthetic fixtures use
    # this conventional path; native export validation still checks actual meshes.
    return '3D/3dmodel.model'


def archive_geometry(z):
    import numpy as np
    cache = {}
    features = set()

    def read(name):
        if name not in cache:
            cache[name] = archive_xml(z, name)
        return cache[name]

    def transform(text):
        if not text:
            return np.eye(4)
        a = [finite(v, '3MF transform') for v in text.split()]
        if len(a) != 12:
            raise ValueError('Malformed 3MF transform')
        return np.array([[a[0], a[3], a[6], a[9]], [a[1], a[4], a[7], a[10]], [a[2], a[5], a[8], a[11]], [0, 0, 0, 1]])

    def component_path(name, attributes):
        target = attributes.get(f'{{{PRODUCTION}}}path', name)
        if target.startswith('/'):
            target = target.lstrip('/')
        elif target != name:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
        if target.startswith('../') or target not in z.namelist():
            raise ValueError('Missing/external 3MF component: ' + target)
        return target

    main = main_model_path(z)
    root = read(main)
    unit = root.get('unit', 'millimeter')
    if unit not in UNITS:
        raise ValueError('Unsupported 3MF unit: ' + unit)

    def geometry(name, oid, matrix, stack=()):
        token = (name, oid)
        if token in stack:
            raise ValueError('Cyclic 3MF component references')
        component = read(name)
        if component.get('unit', 'millimeter') != unit:
            raise ValueError('Mixed-unit component documents are unsupported')
        obj = next((x for x in component.findall('m:resources/m:object', NS) if x.get('id') == oid), None)
        if obj is None:
            raise ValueError('Missing referenced 3MF object')
        arrays, triangle_count = [], 0
        for mesh in obj.findall('m:mesh', NS):
            for triangle in mesh.findall('m:triangles/m:triangle', NS):
                features.update('triangle_attribute:' + key for key in triangle.attrib if key not in {'v1', 'v2', 'v3'})
            features.update('mesh_extension:' + child.tag for child in mesh if child.tag not in {f'{{{CORE}}}vertices', f'{{{CORE}}}triangles'})
            vertices = np.array([[finite(v.get(k), '3MF vertex') for k in ('x', 'y', 'z')] for v in mesh.findall('m:vertices/m:vertex', NS)])
            faces = [[int(t.get(k)) for k in ('v1', 'v2', 'v3')] for t in mesh.findall('m:triangles/m:triangle', NS)]
            if not len(vertices) or not faces:
                raise ValueError('3MF mesh requires vertices and triangle faces')
            face_array = np.asarray(faces)
            if face_array.min() < 0 or face_array.max() >= len(vertices):
                raise ValueError('3MF triangle index is outside vertex array')
            if any(len(set(face)) != 3 for face in faces):
                raise ValueError('3MF triangle has repeated vertex indices')
            areas = np.linalg.norm(np.cross(vertices[face_array[:, 1]] - vertices[face_array[:, 0]], vertices[face_array[:, 2]] - vertices[face_array[:, 0]]), axis=1)
            if np.any(areas <= 1e-14):
                raise ValueError('3MF mesh contains degenerate triangles')
            used = vertices[np.unique(face_array)]
            arrays.append((matrix @ np.column_stack([used, np.ones(len(used))]).T).T[:, :3])
            triangle_count += len(faces)
        for c in obj.findall('m:components/m:component', NS):
            values, count = geometry(component_path(name, c.attrib), c.get('objectid'), matrix @ transform(c.get('transform')), stack + (token,))
            arrays.extend(values)
            triangle_count += count
        if not arrays or triangle_count == 0:
            raise ValueError('Empty 3MF object or unsupported geometry extension')
        return arrays, triangle_count

    result = []
    for index, item in enumerate(root.findall('m:build/m:item', NS)):
        name = component_path(main, item.attrib)
        arrays, count = geometry(name, item.get('objectid'), transform(item.get('transform')))
        values = np.concatenate(arrays) * UNITS[unit]
        if not np.isfinite(values).all():
            raise ValueError('Non-finite transformed 3MF geometry')
        obj = next(x for x in read(name).findall('m:resources/m:object', NS) if x.get('id') == item.get('objectid'))
        bounds = [values.min(axis=0).tolist(), values.max(axis=0).tolist()]
        result.append({'id': item.get('objectid'), 'build_index': index, 'name': obj.get('name'),
                       'printable': item.get('printable', '1') not in ('0', 'false'),
                       'triangles': count, 'bounds_mm': bounds,
                       'dimensions_mm': (values.max(axis=0) - values.min(axis=0)).tolist()})
    for obj in result:
        obj['unsupported_geometry_features'] = sorted(features)
    return result


def inspect_gcode(stream):
    md5 = hashlib.md5()
    position = {'X': 0., 'Y': 0., 'Z': 0., 'E': 0.}
    absolute_xyz, absolute_e = True, True
    moves, bytes_read, headers = 0, 0, []
    for raw in stream:
        md5.update(raw)
        bytes_read += len(raw)
        if len(raw) > 1024 * 1024:
            raise ValueError('G-code line exceeds inspection limit')
        line = raw.decode('utf-8', errors='replace').strip()
        if line.startswith(';') and len(headers) < 80 and len(line) < 250 and any(k in line.lower() for k in ('filament', 'time', 'layer', 'nozzle', 'printer')):
            headers.append(line)
        code = re.sub(r'\([^)]*\)', '', line.split(';', 1)[0]).strip().upper()
        code = re.sub(r'^N\d+\s*', '', code)
        command = re.match(r'^([GMT]\d+(?:\.\d+)?)\b', code)
        if not command:
            continue
        op = command.group(1)
        numbers = {k: float(v) for k, v in re.findall(r'([XYZEFIJK])\s*([-+]?(?:\d+\.?\d*|\.\d+))', code[command.end():])}
        if not all(math.isfinite(x) for x in numbers.values()):
            raise ValueError('Non-finite G-code coordinate')
        if op == 'M82':
            absolute_e = True
        elif op == 'M83':
            absolute_e = False
        elif op == 'G90':
            absolute_xyz = True
        elif op == 'G91':
            absolute_xyz = False
        elif op == 'G92':
            position.update({k: v for k, v in numbers.items() if k in position})
        elif op in ('G0', 'G00', 'G1', 'G01', 'G2', 'G02', 'G3', 'G03'):
            updated = dict(position)
            for axis in 'XYZE':
                if axis in numbers:
                    absolute = absolute_e if axis == 'E' else absolute_xyz
                    updated[axis] = numbers[axis] if absolute else position[axis] + numbers[axis]
            travel = math.hypot(updated['X'] - position['X'], updated['Y'] - position['Y']) > 1e-8
            arc = op in ('G2', 'G02', 'G3', 'G03') and any(abs(numbers.get(k, 0)) > 1e-8 for k in 'IJ')
            if updated['E'] - position['E'] > 1e-8 and (travel or arc):
                moves += 1
            position = updated
    return {'bytes': bytes_read, 'extrusion_moves': moves, 'md5': md5.hexdigest(), 'headers': headers}


def local_settings(root, names):
    """Capture local process/material overrides, excluding generated provenance."""
    records = []
    ignored = {'name', 'matrix', 'source_file', 'source_object_id', 'source_volume_id',
               'source_offset_x', 'source_offset_y', 'source_offset_z', 'face_count'}
    for obj in root.findall('object'):
        name = names.get(obj.get('id')) or next((e.get('value') for e in obj.findall('metadata') if e.get('key') == 'name'), None)
        params = {e.get('key'): e.get('value') for e in obj.findall('metadata') if e.get('key') is not None and e.get('key') not in ignored}
        parts = []
        for part in obj.findall('part'):
            data = {e.get('key'): e.get('value') for e in part.findall('metadata') if e.get('key') is not None and e.get('key') not in ignored}
            parts.append({'subtype': part.get('subtype', 'normal_part'), 'settings': data})
        records.append({'name': name, 'settings': params, 'parts': parts})
    return sorted(records, key=lambda x: canonical(x))


def editing_members(z, names):
    """Recognize empty/default native bookkeeping, reject active editing data."""
    unsupported = []
    for name in names:
        if posixpath.basename(name) not in UNVERIFIED_EDITING_MEMBERS:
            continue
        if z.getinfo(name).file_size > 16 * 1024 ** 2:
            unsupported.append(name)
            continue
        raw = z.read(name).strip()
        if not raw:
            continue
        if name.endswith('.xml'):
            root = archive_xml(z, name)
            if not len(root) and not (root.text or '').strip():
                continue
            if name.endswith('cut_information.xml') and root.tag == 'objects':
                # Studio writes one zero-ID marker per untouched object.
                default_cut = all(obj.tag == 'object' and len(obj) == 1 and obj[0].tag == 'cut_id'
                                  and obj[0].attrib == {'id': '0', 'check_sum': '1', 'connectors_cnt': '0'}
                                  and not len(obj[0]) for obj in root)
                if default_cut:
                    continue
        elif name.endswith('.json') and json.loads(raw) in ({}, []):
            continue
        unsupported.append(name)
    return unsupported


def inspect_3mf(path):
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        names = checked_archive(z)
        result = {'file': path.name, 'sha256': digest(path), 'entries': len(names),
                  'model_parts': [n for n in names if n.endswith('.model')],
                  'gcode_files': [n for n in names if n.endswith('.gcode')], 'project_settings': None,
                  'metadata': {}, 'plates': [], 'gcode_headers': {}, 'toolpaths': {}, 'local_settings': [],
                  'unsupported_editing_members': editing_members(z, names),
                  'plate_settings': [], 'assembly_state': []}
        configs_found = [n for n in names if n.endswith('project_settings.config')]
        if len(configs_found) > 1:
            raise ValueError('Ambiguous project settings')
        if configs_found:
            if z.getinfo(configs_found[0]).file_size > 16 * 1024 ** 2:
                raise ValueError('Project settings exceed inspection limit')
            settings = json.loads(z.read(configs_found[0]))
            if not isinstance(settings, dict):
                raise ValueError('Project settings must be an object')
            result['project_settings'] = settings
        result['build_objects'] = archive_geometry(z) if result['model_parts'] else []
        object_names = {o['id']: o['name'] for o in result['build_objects']}
        for name in names:
            if name.endswith(('slice_info.config', 'model_settings.config')):
                root = archive_xml(z, name)
                result['metadata'][name] = [e.attrib for e in root.iter() if e.attrib]
                if name.endswith('slice_info.config'):
                    result['plates'] = [{e.get('key'): e.get('value') for e in plate.findall('metadata')} for plate in root.findall('plate')]
                else:
                    for obj in root.findall('object'):
                        label = next((e.get('value') for e in obj.findall('metadata') if e.get('key') == 'name'), None)
                        if label:
                            object_names[obj.get('id')] = label
                    result['local_settings'] = local_settings(root, object_names)
                    result['model_plates'] = [{e.get('key'): e.get('value') for e in p.findall('metadata')} for p in root.findall('plate')]
                    result['unsupported_local_features'] = sorted({e.tag for e in root if e.tag not in {'object', 'plate', 'assemble'}})
                    for obj in root.findall('object'):
                        result['unsupported_local_features'].extend('object_child:' + e.tag for e in obj if e.tag not in {'metadata', 'part'})
                        for part in obj.findall('part'):
                            if part.get('subtype', 'normal_part') not in SUPPORTED_PART_TYPES:
                                result['unsupported_local_features'].append('part_subtype:' + part.get('subtype'))
                            result['unsupported_local_features'].extend('part_child:' + e.tag for e in part if e.tag not in {'metadata', 'mesh_stat'})
                        for metadata in obj.iter('metadata'):
                            if metadata.get('key') is None and set(metadata.attrib) != {'face_count'}:
                                result['unsupported_local_features'].append('unparsed_metadata:' + canonical(metadata.attrib))
                    generated_plate_keys = {'plater_id', 'gcode_file', 'thumbnail_file', 'top_file', 'pick_file', 'pattern_bbox_file'}
                    result['plate_settings'] = [{k: v for k, v in plate.items() if k not in generated_plate_keys} for plate in result['model_plates']]
                    for item in root.findall('assemble/assemble_item'):
                        state = dict(item.attrib)
                        if 'object_id' in state:
                            state['object_id'] = object_names.get(state['object_id'], state['object_id'])
                        result['assembly_state'].append(state)
                    result['assembly_state'].sort(key=canonical)
        for obj in result['build_objects']:
            obj['name'] = object_names.get(obj['id'])
        for name in result['gcode_files']:
            with z.open(name) as stream:
                stats = inspect_gcode(stream)
            stats['checksum'] = 'not_present'
            if name + '.md5' in names:
                if z.getinfo(name + '.md5').file_size > 128:
                    raise ValueError('Invalid G-code MD5 member')
                expected = z.read(name + '.md5').decode('ascii').strip().lower()
                if not re.fullmatch('[0-9a-f]{32}', expected) or stats['md5'] != expected:
                    raise ValueError('G-code MD5 mismatch: ' + name)
                stats['checksum'] = 'verified'
            result['gcode_headers'][name] = stats.pop('headers')
            result['toolpaths'][name] = stats
        result['has_model'] = any(o['printable'] for o in result['build_objects'])
        result['has_toolpaths'] = bool(result['toolpaths']) and all(t['extrusion_moves'] > 0 for t in result['toolpaths'].values())
        result['has_machine_identification'] = bool(result['plates']) and all(p.get('printer_model_id') for p in result['plates'])
        return result


def compare_geometry(expected, actual):
    import numpy as np
    if len(expected) != len(actual):
        raise ValueError('Exported object count differs from prepared/source project')
    expected_names = [o.get('identity') or o.get('name') for o in expected]
    actual_names = [o.get('name') for o in actual]
    if any(not n for n in expected_names + actual_names) or len(set(expected_names)) != len(expected_names) or set(expected_names) != set(actual_names):
        raise ValueError('Exported object identities are missing, duplicated or changed')
    by_name = {o['name']: o for o in actual}
    for name, obj in zip(expected_names, expected):
        counterpart = by_name[name]
        bounds = obj.get('placed_bounds_mm', obj.get('bounds_mm'))
        dimensions = obj.get('placed_dimensions_mm', obj.get('dimensions_mm'))
        for label, left, right in [('bounds', bounds, counterpart['bounds_mm']), ('dimensions', dimensions, counterpart['dimensions_mm'])]:
            if not np.allclose(left, right, atol=BOUNDS_TOLERANCE_MM, rtol=0):
                raise ValueError(f'Exported {label} mismatch for {name} (tolerance {BOUNDS_TOLERANCE_MM} mm)')
        if obj.get('printable', True) != counterpart.get('printable', True):
            raise ValueError('Exported object printability changed: ' + name)


def native_project_capability(report):
    settings = report.get('project_settings')
    if not isinstance(settings, dict) or not report['has_model']:
        raise ValueError('reslice requires an editable native Studio project with embedded settings')
    for key in ('printer_model', 'printer_settings_id', 'print_settings_id', 'curr_bed_type'):
        if not settings.get(key):
            raise ValueError('Native project lacks hardware/process identity: ' + key)
    supported_hardware(settings, require_material=True)
    plates = report.get('model_plates') or report.get('plates')
    if not plates or len(plates) != 1:
        raise ValueError('reslice automation requires exactly one native plate')
    if report.get('unsupported_local_features'):
        raise ValueError('Unverified native project features: ' + ', '.join(report['unsupported_local_features']))
    unsupported = report.get('unsupported_editing_members', []) + [f for o in report['build_objects'] for f in o.get('unsupported_geometry_features', [])]
    if unsupported:
        raise ValueError('Unverified native editing/painting features: ' + ', '.join(sorted(set(unsupported))))
    if any(not o['printable'] for o in report['build_objects']):
        raise ValueError('reslice requires all build objects to be printable')
    names = [o['name'] for o in report['build_objects']]
    if any(not x for x in names) or len(set(names)) != len(names):
        raise ValueError('reslice requires unique object names to verify preservation')
    # No custom executable post-processing. The helper does not inject/execute
    # archive data; native vendor G-code is preserved as part of the project.
    if settings.get('post_process'):
        raise ValueError('Native post-process commands are not supported')
    for obj in report['local_settings']:
        for local in [obj['settings'], *(part['settings'] for part in obj['parts'])]:
            if local.get('post_process'):
                raise ValueError('Native local post-process commands are not supported')
            for key in ('extruder', 'extruder_id', 'wall_filament', 'solid_infill_filament', 'sparse_infill_filament', 'support_filament', 'support_interface_filament'):
                if key in local and str(local[key]) not in ('0', '1'):
                    raise ValueError('Native local setting references an unsupported filament/extruder: ' + key)


def compare_project_settings(expected, actual):
    if not isinstance(actual, dict):
        raise ValueError('Exported project lacks settings')
    # These identify native application/version bookkeeping, not print intent.
    ignored = {'version', 'compatible_printers', 'compatible_prints', 'print_compatible_printers',
               'inherits_group', 'different_settings_to_system', 'filament_self_index'}
    for key, value in expected.items():
        if key not in ignored and actual.get(key) != value:
            raise ValueError('Native project setting changed during reslice: ' + key)


def _begin_job(output):
    output = Path(output).expanduser().resolve()
    report_path = output.with_suffix('.report.json')
    if output.exists() or report_path.exists():
        raise FileExistsError('Refusing to overwrite output/report: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix='.' + output.stem + '.job-', dir=output.parent))
    return output, report_path, job


def _run_cli(env, job, inputs, options, timeout):
    required = ('--slice', '--export-3mf', '--arrange', '--orient', '--outputdir')
    if not all(env.get('supports', {}).get(flag) for flag in required):
        raise ValueError('Installed CLI lacks required features: ' + ', '.join(required))
    staged = job / 'sliced.3mf'
    command = [env['binary'], '--arrange', '0', '--orient', '0', '--slice', '0', '--debug', '2',
               '--outputdir', str(job), '--export-3mf', staged.name, *options, *map(str, inputs)]
    dump({'argv': command, 'software': env['version']}, job / 'invocation.json')
    try:
        run = subprocess.run(command, cwd=str(job), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def text_part(part):
            return part.decode('utf-8', errors='replace') if isinstance(part, bytes) else part or ''
        (job / 'slicer.log').write_text(text_part(exc.stdout) + '\n' + text_part(exc.stderr), encoding='utf-8')
        raise RuntimeError(f'Slicing timed out; diagnostics: {job}') from exc
    combined = run.stdout + '\n' + run.stderr
    (job / 'slicer.log').write_text(combined, encoding='utf-8')
    native = read_json(job / 'result.json') if (job / 'result.json').is_file() else None
    if run.returncode or (native is not None and native.get('return_code') != 0) or not staged.is_file():
        raise RuntimeError(f'Slicing failed ({run.returncode}); diagnostics: {job}')
    return staged, combined, native


def validate_slice_report(report):
    if not report['has_model'] or not report['has_toolpaths']:
        raise ValueError('Exported project has no printable mesh or no actual extrusion paths')
    if not isinstance(report['project_settings'], dict):
        raise ValueError('Exported project lacks settings')
    supported_hardware(report['project_settings'], require_material=True)
    if len(report['gcode_files']) != 1:
        raise ValueError('Automation requires one sliced plate')


def classify_messages(text, version, settings):
    messages = [line for line in text.splitlines() if '[error]' in line.lower() or '[warning]' in line.lower()]
    known, unexpected = [], []
    for line in messages:
        if '[error]' not in line.lower():
            continue
        official_t = '02.08.04.57' in version and 'Invalid T command' in line and 'T65535' in line and 'T65535' in str(settings.get('machine_end_gcode', ''))
        (known if official_t else unexpected).append(line)
    if unexpected:
        raise ValueError('Unexpected native error messages: ' + '\n'.join(unexpected))
    return messages, known


def _publish(staged, output, report_path, report, job):
    report.update({'file': output.name, 'status': 'passed', 'software_validation': 'passed',
                   'native_gui_reopen': 'not_run', 'physical_print': 'not_run', 'diagnostics_dir': str(job)})
    staged_report = job / 'validated.report.json'
    dump(report, staged_report)
    # Same-volume exclusive hard links publish complete files without overwriting
    # another job's result. Source/intermediate files remain in diagnostics.
    os.link(staged_report, report_path)
    try:
        os.link(staged, output)
    except BaseException:
        report_path.unlink()
        raise
    return report


def _failure(job, error):
    dump({'status': 'failed', 'error': str(error), 'physical_print': 'not_run'}, job / 'failure.json')


def slice_job(env, config_dir, manifest, output, bed, timeout=1800):
    if not bed or not isinstance(bed, str):
        raise ValueError('Explicit build plate is required')
    data = {kind: read_json(Path(config_dir) / (kind + '.json')) for kind in ('machine', 'process', 'filament')}
    validate_effective_configs(data)
    if not all(env.get('supports', {}).get(flag) for flag in ('--load-settings', '--load-filaments')):
        raise ValueError('Installed CLI lacks config loading support')
    for kind in data:
        for key in ('name', 'inherits'):
            if not data[kind].get(key):
                raise ValueError(f'{kind} config lacks canonical identity {key}')
    manifest = load_manifest(manifest) if isinstance(manifest, (str, Path)) else copy.deepcopy(manifest)
    manifest = effective_manifest(manifest, data['process'])
    meshes, check = prepare_geometry(manifest, data['machine'])
    if check['status'] != 'passed':
        raise ValueError('Preflight failed: ' + '; '.join(check['errors']))
    output, report_path, job = _begin_job(output)
    try:
        dump(manifest, job / 'manifest.json')
        dump(check, job / 'preflight.json')
        config_copy = job / 'config'
        config_copy.mkdir()
        for kind, d in data.items():
            dump(d, config_copy / (kind + '.json'))
        prepared = job / 'prepared.3mf'
        stage_3mf(meshes, check, prepared)
        compare_geometry(check['objects'], inspect_3mf(prepared)['build_objects'])
        staged, logs, native = _run_cli(env, job, [prepared],
            ['--load-settings', str(config_copy / 'machine.json') + ';' + str(config_copy / 'process.json'),
             '--load-filaments', str(config_copy / 'filament.json'), '--curr-bed-type', bed], timeout)
        report = inspect_3mf(staged)
        validate_slice_report(report)
        compare_geometry(check['objects'], report['build_objects'])
        settings = report['project_settings']
        for key, expected in [('curr_bed_type', bed), ('printer_model', data['machine'].get('printer_model')),
                              ('nozzle_diameter', data['machine']['nozzle_diameter']),
                              ('printer_settings_id', data['machine'].get('printer_settings_id')),
                              ('print_settings_id', data['process'].get('print_settings_id')),
                              ('filament_settings_id', data['filament'].get('filament_settings_id'))]:
            if expected is None or settings.get(key) != expected:
                raise ValueError('Exported hardware/profile identity mismatch: ' + key)
        for kind, expected in data.items():
            changes = expected.get('different_settings_to_system', [''])
            if not isinstance(changes, list) or len(changes) != 1:
                raise ValueError('Unsupported override difference format')
            for key in changes[0].split(';'):
                if key and (key not in expected or settings.get(key) != expected[key]):
                    raise ValueError('Exported override mismatch: ' + key)
        for key in ('print_sequence', 'brim_width', 'brim_object_gap'):
            if key in data['process'] and settings.get(key) != data['process'][key]:
                raise ValueError('Effective preflight/process mismatch: ' + key)
        report['slicer_messages'], report['known_native_errors'] = classify_messages(logs, env['version'], data['machine'])
        report.update({'software_version': env['version'], 'native_result': native, 'preflight': check,
                       'prepared_sha256': digest(prepared), 'geometry_tolerance_mm': BOUNDS_TOLERANCE_MM,
                       'mode': 'manifest_slice'})
        return _publish(staged, output, report_path, report, job)
    except Exception as exc:
        _failure(job, exc)
        raise RuntimeError(f'{exc}; diagnostics: {job}') from exc


def reslice_job(env, project, output, timeout=1800):
    source = Path(project).expanduser().resolve()
    source_report = inspect_3mf(source)
    native_project_capability(source_report)
    output, report_path, job = _begin_job(output)
    try:
        snapshot = job / 'source.3mf'
        shutil.copyfile(source, snapshot)
        if digest(snapshot) != source_report['sha256']:
            raise ValueError('Source project changed during inspection')
        dump(source_report, job / 'source.report.json')
        if not env.get('supports', {}).get('--load-filaments'):
            raise ValueError('Native reslice requires empty-slot filament retention support')
        # One quoted empty slot retains the embedded filament without loading a
        # replacement. In 02.08.04.57 this also avoids the CLI upload-mode branch
        # that silently resets filament_prime_volume to 45 when no slot list was
        # supplied (BambuStudio.cpp:6438). Never disable native checks to avoid it.
        staged, logs, native = _run_cli(env, job, [snapshot], ['--load-filaments', '""'], timeout)
        report = inspect_3mf(staged)
        validate_slice_report(report)
        native_project_capability(report)
        compare_geometry(source_report['build_objects'], report['build_objects'])
        if report['local_settings'] != source_report['local_settings']:
            raise ValueError('Native object/part overrides changed during reslice')
        if report['plate_settings'] != source_report['plate_settings']:
            raise ValueError('Native plate overrides changed during reslice')
        if report['assembly_state'] != source_report['assembly_state']:
            raise ValueError('Native assembly state changed during reslice')
        compare_project_settings(source_report['project_settings'], report['project_settings'])
        report['slicer_messages'], report['known_native_errors'] = classify_messages(logs, env['version'], source_report['project_settings'])
        report.update({'software_version': env['version'], 'native_result': native, 'source_sha256': source_report['sha256'],
                       'geometry_tolerance_mm': BOUNDS_TOLERANCE_MM, 'mode': 'native_reslice'})
        return _publish(staged, output, report_path, report, job)
    except Exception as exc:
        _failure(job, exc)
        raise RuntimeError(f'{exc}; diagnostics: {job}') from exc


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    class CLIParser(argparse.ArgumentParser):
        def error(self, message):
            if self.prog.endswith(' slice') and '--manifest' in message and 'required' in message:
                message += '. Migrate to: slice --manifest manifest.json --config-dir configs --bed "Textured PEI Plate" --output job.3mf. Minimal manifest: {"objects":[{"path":"model.stl","units":"mm","center_xy_mm":[100,100]}]}'
            super().error(message)
    parser = CLIParser(description=__doc__)
    parser.add_argument('--binary')
    parser.add_argument('--profiles')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('env')
    q = sub.add_parser('profiles')
    for field in ('machine', 'process', 'filament', 'output'):
        q.add_argument('--' + field, required=True)
    q.add_argument('--variant', default='Direct Drive Standard')
    q.add_argument('--overrides')
    q = sub.add_parser('preflight')
    q.add_argument('manifest')
    q.add_argument('--machine-json', required=True)
    q.add_argument('--process-json')
    q.add_argument('--output')
    q = sub.add_parser('inspect')
    q.add_argument('file')
    q.add_argument('--output')
    q = sub.add_parser('slice', description='Use an explicit-units manifest. Legacy positional models and --keep-placement are unsupported.')
    for field in ('manifest', 'config-dir', 'output', 'bed'):
        q.add_argument('--' + field, required=True)
    q = sub.add_parser('reslice', description='Preserve a one-plate, one-material standard-hotend native project.')
    q.add_argument('--project', required=True)
    q.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.cmd == 'inspect':
        dump(inspect_3mf(args.file), args.output)
    elif args.cmd == 'preflight':
        report = preflight(load_manifest(args.manifest), read_json(args.machine_json), read_json(args.process_json) if args.process_json else None)
        dump(report, args.output)
        if report['status'] != 'passed':
            raise SystemExit(2)
    else:
        env = discover(args.binary, args.profiles)
        if args.cmd == 'env':
            dump(env)
        elif args.cmd == 'profiles':
            dump(write_configs(env, args))
        else:
            report = slice_job(env, args.config_dir, args.manifest, args.output, args.bed) if args.cmd == 'slice' else reslice_job(env, args.project, args.output)
            dump({k: v for k, v in report.items() if k not in ('project_settings', 'metadata', 'gcode_headers')})


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, ImportError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
