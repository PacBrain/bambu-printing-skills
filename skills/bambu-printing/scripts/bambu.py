#!/usr/bin/env python3
"""Offline Bambu Studio preparation. Never connects to a printer or starts printing."""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, platform, shutil, subprocess, sys, zipfile
import xml.etree.ElementTree as ET

Path = pathlib.Path

def dump(value, target=None):
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if target:
        p=Path(target); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8')
    else: print(text)
    return value

def discover(binary=None, profiles=None):
    candidates=[binary,os.environ.get('BAMBU_STUDIO_BIN'),shutil.which('bambu-studio'),shutil.which('BambuStudio')]
    if sys.platform=='darwin': candidates.append('/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')
    if sys.platform=='win32': candidates.append(str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Bambu Studio/bambu-studio.exe'))
    exe=next((Path(p) for p in candidates if p and Path(p).is_file()),None)
    if not exe: raise FileNotFoundError('Bambu Studio not found; supply --binary or BAMBU_STUDIO_BIN')
    run=subprocess.run([str(exe),'--help'],capture_output=True,text=True,timeout=30)
    if run.returncode: raise RuntimeError(run.stderr or run.stdout)
    roots=[profiles,os.environ.get('BAMBU_PROFILES'),exe.parent.parent/'Resources/profiles/BBL',exe.parent/'resources/profiles/BBL',Path('/usr/share/BambuStudio/profiles/BBL')]
    root=next((Path(p) for p in roots if p and (Path(p)/'machine').is_dir()),None)
    if not root: raise FileNotFoundError('Official BBL profile directory not found; supply --profiles')
    return {'binary':str(exe),'profiles':str(root),'platform':platform.platform(),
            'version':next((x.strip(':') for x in run.stdout.splitlines() if x.startswith('BambuStudio-')),'unknown'),
            'supports':{x:x in run.stdout for x in ['--load-settings','--load-filaments','--slice','--export-3mf']}}

class Profiles:
    """Merge parents and included fragments before explicit child overrides."""
    def __init__(self,root):
        self.root=Path(root); self.maps={}; self.trace=[]
        for kind in ['machine','process','filament']:
            self.maps[kind]={}
            for p in (self.root/kind).rglob('*.json'):
                d=json.loads(p.read_text(encoding='utf-8'))
                for name in [p.stem,d.get('name')]:
                    if name:
                        old=self.maps[kind].get(name)
                        if old and old!=p: raise ValueError('Duplicate profile name: '+name)
                        self.maps[kind][name]=p

    def resolve(self,kind,name,stack=()):
        token=(kind,name)
        if token in stack: raise ValueError('Profile inheritance/include cycle: '+repr(stack+(token,)))
        p=self.maps[kind].get(name)
        if p is None: raise ValueError(f'Missing {kind} profile: {name}')
        d=json.loads(p.read_text(encoding='utf-8')); result={}
        parent=d.get('inherits')
        if parent: result.update(self.resolve(kind,parent,stack+(token,)))
        includes=d.get('include',[])
        if isinstance(includes,str): includes=[includes]
        for child in includes: result.update(self.resolve(kind,child,stack+(token,)))
        result.update({k:v for k,v in d.items() if k not in ['inherits','include']})
        record={'kind':kind,'name':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        if record not in self.trace: self.trace.append(record)
        return result

def configs(env,machine,process,filament,overrides=None,variant='Direct Drive Standard'):
    lib=Profiles(env['profiles'])
    resolved={k:lib.resolve(k,n) for k,n in [('machine',machine),('process',process),('filament',filament)]}
    if len(resolved['machine'].get('nozzle_diameter',[]))!=1:
        raise ValueError('Automated multi-extruder profiles are not validated; prepare them in native Studio')
    for k in ['process','filament']:
        allowed=resolved[k].get('compatible_printers',[])
        if allowed and machine not in allowed: raise ValueError(f'{k} incompatible with {machine}')
    variants=resolved['machine'].get('printer_extruder_variant',[])
    if variants and variant not in variants: raise ValueError('Unsupported extruder variant: '+variant)
    # Preserve vendor variant arrays. Bambu Studio selects a variant internally;
    # do not truncate arbitrary arrays (axis limits and compatibility lists differ).
    for k,d in resolved.items():
        d['from']='User';d['instantiation']='true'
        base=d['name']; d['inherits']=base; d['name']=base+' - Prepared'
        # CLI uses inherits as the canonical system identity for user presets,
        # even when every numerical setting has already been flattened.
        if k=='machine': d['printer_settings_id']=d['name']
        if k=='process': d['print_settings_id']=d['name']
        if k=='filament': d['filament_settings_id']=[d['name']]
    # Use native extruder state selection; default "standard" is tested.
    if variant!='Direct Drive Standard':
        raise ValueError('Automated non-standard hotends are not validated. Export a project from Studio with the actual hotend selected.')
    if overrides:
        for kind,changes in overrides.items():
            if kind not in resolved or not isinstance(changes,dict):raise ValueError('Overrides must be machine/process/filament objects')
            for key,value in changes.items():
                if 'gcode' in key.lower():raise ValueError('This helper does not override machine/filament G-code')
                if key=='only_one_wall_top':raise ValueError('Deprecated key only_one_wall_top is ignored by current Studio; use top_one_wall_type: "not apply", "all top", or "topmost"')
                runtime_defaults={'process':{'brim_type','only_one_wall_first_layer','timelapse_type','top_one_wall_type'}}
                if key not in resolved[kind] and key not in runtime_defaults.get(kind,set()):raise ValueError(f'Unknown {kind} key: {key}')
                resolved[kind][key]=value
    for kind,d in resolved.items():
        # Studio re-applies installed system profiles when reopening a project.
        # Without this explicit diff list it silently discards job overrides.
        d['different_settings_to_system']=[';'.join(sorted((overrides or {}).get(kind,{})))]
    return resolved,lib.trace

def write_configs(env,args):
    overrides=json.loads(Path(args.overrides).read_text()) if args.overrides else None
    data,trace=configs(env,args.machine,args.process,args.filament,overrides,args.variant)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    for kind,d in data.items():dump(d,out/(kind+'.json'))
    dump({'software':env['version'],'variant':args.variant,'sources':trace},out/'provenance.json')
    return {k:str(out/(k+'.json')) for k in data}

def mesh_info(path,units):
    import numpy as np
    import trimesh
    if units not in ['mm','cm','m','inch']:raise ValueError('Explicit source units are required')
    scale={'mm':1,'cm':10,'m':1000,'inch':25.4}[units]
    mesh=trimesh.load_mesh(str(path),process=True)
    if not isinstance(mesh,trimesh.Trimesh):raise ValueError('Use one STL per object; scenes are not accepted')
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():raise ValueError('Empty/non-finite mesh')
    mesh.apply_scale(scale)
    counts=np.bincount(mesh.edges_unique_inverse)
    report={'name':Path(path).name,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'units':'mm','source_units':units,'dimensions_mm':mesh.extents.tolist(),'bounds_mm':mesh.bounds.tolist(),
            'vertices':len(mesh.vertices),'triangles':len(mesh.faces),'watertight':bool(mesh.is_watertight),
            'winding_consistent':bool(mesh.is_winding_consistent),'positive_volume':bool(mesh.volume>0),
            'volume_mm3':float(mesh.volume),'nonmanifold_edges':int(sum(counts>2)),
            'self_intersections':'not_run','minimum_wall_thickness':'not_run'}
    if not all(report[k] for k in ['watertight','winding_consistent','positive_volume']) or report['nonmanifold_edges']:
        raise ValueError('Mesh is not a consistently oriented closed volume: '+json.dumps(report))
    return mesh,report

def preflight(manifest,machine):
    import numpy as np
    from shapely.geometry import Polygon,box
    from shapely import affinity
    def pts(values):return [tuple(map(float,v.split('x'))) for v in values]
    bed=Polygon(pts(machine['printable_area']))
    excludes=[]
    for key in ['bed_exclude_area','wrapping_exclude_area']:
        if machine.get(key):excludes.append((key,Polygon(pts(machine[key]))))
    for region in manifest.get('additional_exclude_areas',[]):excludes.append(('job_exclusion',Polygon(region)))
    footprints=[];objects=[];fail=[]
    clearance=float(manifest.get('brim_width_mm',0))+float(manifest.get('brim_gap_mm',0))
    if clearance<0:raise ValueError('Negative brim clearance')
    for obj in manifest['objects']:
        mesh,info=mesh_info(obj['path'],obj.get('units'))
        mesh.vertices-=np.array([*mesh.bounds.mean(axis=0)[:2],mesh.bounds[0,2]])
        angle=float(obj.get('rotation_z_deg',0));mesh.apply_transform(__import__('trimesh').transformations.rotation_matrix(np.deg2rad(angle),[0,0,1]))
        x,y=map(float,obj['center_xy_mm']);mesh.apply_translation([x,y,0])
        a,b=mesh.bounds
        # Conservative XY bounds, not an optimistic area-only test.
        footprint=box(a[0],a[1],b[0],b[1]).buffer(clearance,join_style=2)
        if not bed.covers(footprint):fail.append(info['name']+': outside printable area including brim')
        for name,zone in excludes:
            if footprint.intersects(zone):fail.append(info['name']+': intersects '+name)
        if b[2]>float(machine['printable_height']):fail.append(info['name']+': exceeds printable height')
        for prev in footprints:
            if footprint.intersects(prev):fail.append(info['name']+': overlapping model/brim footprint')
        footprints.append(footprint);info['placed_bounds_mm']=[a.tolist(),b.tolist()];objects.append(info)
    seq=manifest.get('print_sequence','by layer')
    if seq=='by object' and len(objects)>1:
        radius=float(machine.get('extruder_clearance_radius',0))
        height=float(machine.get('extruder_clearance_height_to_rod',0))
        if radius<=0 or height<=0:fail.append('Sequential-print head clearance unavailable')
        for i,obj in enumerate(objects[:-1]):
            if obj['dimensions_mm'][2]>height:fail.append(obj['name']+': exceeds conservative sequential head clearance')
            for other in footprints[i+1:]:
                if footprints[i].buffer(radius).intersects(other):fail.append(obj['name']+': sequential head collision envelope overlaps')
    elif seq!='by layer':raise ValueError('Unknown print sequence')
    return {'status':'failed' if fail else 'passed','objects':objects,'errors':fail,
            'scope':'Conservative static bounds only; slicer toolpaths, purge/calibration areas and physical printing still require checks.'}

def inspect_3mf(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist(); result={'file':Path(path).name,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'entries':len(names)}
        result['model_parts']=[n for n in names if n.endswith('.model')]
        result['gcode_files']=[n for n in names if n.endswith('.gcode')]
        configs=[n for n in names if n.endswith('project_settings.config')]
        result['project_settings']=json.loads(z.read(configs[0])) if configs else None
        result['metadata']={}
        for n in names:
            if n.endswith(('slice_info.config','model_settings.config')):
                root=ET.fromstring(z.read(n));result['metadata'][n]=[e.attrib for e in root.iter() if e.attrib]
                if n.endswith('slice_info.config'):
                    result['plates']=[{e.get('key'):e.get('value') for e in plate.findall('metadata')} for plate in root.findall('plate')]
        result['gcode_headers']={}
        for n in result['gcode_files']:
            with z.open(n) as f:head=f.read(32000).decode('utf-8',errors='replace')
            result['gcode_headers'][n]=[line for line in head.splitlines() if line.startswith(';') and len(line)<250 and any(k in line.lower() for k in ['filament','time','layer','nozzle','printer'])][:80]
        result['has_model']=bool(result['model_parts']);result['has_toolpaths']=bool(result['gcode_files'])
        result['build_objects']=archive_geometry(z) if result['has_model'] else []
        result['has_model']=bool(result['build_objects'])
        result['has_machine_identification']=bool(result.get('plates')) and all(p.get('printer_model_id') for p in result['plates'])
        return result

def archive_geometry(z):
    """Follow 3MF Production Extension component references and transforms."""
    import numpy as np
    import posixpath
    ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
    cache={}
    def read(name):
        name=name.lstrip('/')
        if name not in cache:cache[name]=ET.fromstring(z.read(name))
        return cache[name]
    def transform(text):
        if not text:return np.eye(4)
        a=list(map(float,text.split()))
        if len(a)!=12:raise ValueError('Malformed 3MF transform')
        return np.array([[a[0],a[3],a[6],a[9]],[a[1],a[4],a[7],a[10]],[a[2],a[5],a[8],a[11]],[0,0,0,1]])
    def points(name,oid,matrix,stack=()):
        token=(name,oid)
        if token in stack:raise ValueError('Cyclic 3MF component references')
        root=read(name);obj=root.find(f"m:resources/m:object[@id='{oid}']",ns)
        if obj is None:raise ValueError('Missing referenced 3MF object')
        result=[]
        for v in obj.findall('m:mesh/m:vertices/m:vertex',ns):result.append((matrix@np.array([float(v.get('x')),float(v.get('y')),float(v.get('z')),1]))[:3])
        for c in obj.findall('m:components/m:component',ns):
            target=next((v for k,v in c.attrib.items() if k.endswith('}path')),name)
            if target.startswith('/'):target=target.lstrip('/')
            elif target!=name:target=posixpath.normpath(posixpath.join(posixpath.dirname(name),target))
            result.extend(points(target,c.get('objectid'),matrix@transform(c.get('transform')),stack+(token,)))
        return result
    main='3D/3dmodel.model';root=read(main)
    unit=root.get('unit','millimeter');scale={'micron':.001,'millimeter':1,'centimeter':10,'meter':1000,'inch':25.4,'foot':304.8}.get(unit)
    if scale is None:raise ValueError('Unsupported 3MF unit: '+unit)
    out=[]
    for item in root.findall('m:build/m:item',ns):
        values=np.array(points(main,item.get('objectid'),transform(item.get('transform'))))*scale
        if not len(values):raise ValueError('Empty 3MF build object')
        bounds=[values.min(axis=0).tolist(),values.max(axis=0).tolist()]
        out.append({'id':item.get('objectid'),'bounds_mm':bounds,'dimensions_mm':(values.max(axis=0)-values.min(axis=0)).tolist()})
    return out

def slice_job(env,config_dir,models,output,bed,arrange=True,orient=False,timeout=1800):
    if not all(env['supports'].values()):raise RuntimeError('Installed CLI lacks required features')
    config_dir=Path(config_dir);output=Path(output)
    if output.exists():raise FileExistsError('Refusing to overwrite '+str(output))
    output.parent.mkdir(parents=True,exist_ok=True)
    args=[env['binary'],'--load-settings',str(config_dir/'machine.json')+';'+str(config_dir/'process.json'),
          '--load-filaments',str(config_dir/'filament.json'),'--orient','1' if orient else '0',
          '--arrange','1' if arrange else '0','--curr-bed-type',bed,'--slice','0','--debug','2','--export-3mf',str(output)]
    args.extend(map(str,models))
    run=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    log=output.with_suffix('.log');log.write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
    if run.returncode or not output.is_file():raise RuntimeError(f'Slicing failed ({run.returncode}); inspect {log}')
    report=inspect_3mf(output)
    if not report['has_model'] or not report['has_toolpaths']:raise RuntimeError('CLI exported no model/toolpath data')
    if report['project_settings'].get('curr_bed_type')!=bed:raise RuntimeError('Exported build plate differs from requested plate')
    for kind in ['machine','process','filament']:
        expected=json.loads((config_dir/(kind+'.json')).read_text())
        for key in expected.get('different_settings_to_system',[''])[0].split(';'):
            if key and report['project_settings'].get(key)!=expected[key]:
                raise RuntimeError(f'Output override mismatch for {key}: expected {expected[key]!r}, got {report["project_settings"].get(key)!r}')
    report['slicer_messages']=[x for x in (run.stdout+'\n'+run.stderr).splitlines() if '[error]' in x or '[warning]' in x]
    report['physical_print']='not_run'
    report['software_version']=env['version'];dump(report,output.with_suffix('.report.json'))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary');p.add_argument('--profiles')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('env')
    q=sub.add_parser('profiles');q.add_argument('--machine',required=True);q.add_argument('--process',required=True);q.add_argument('--filament',required=True);q.add_argument('--variant',default='Direct Drive Standard');q.add_argument('--overrides');q.add_argument('--output',required=True)
    q=sub.add_parser('preflight');q.add_argument('manifest');q.add_argument('--machine-json',required=True);q.add_argument('--output')
    q=sub.add_parser('inspect');q.add_argument('file');q.add_argument('--output')
    q=sub.add_parser('slice');q.add_argument('--config-dir',required=True);q.add_argument('--output',required=True);q.add_argument('--bed',required=True);q.add_argument('--keep-placement',action='store_true');q.add_argument('models',nargs='+')
    a=p.parse_args()
    if a.cmd=='inspect':dump(inspect_3mf(a.file),a.output)
    elif a.cmd=='preflight':
        report=preflight(json.loads(Path(a.manifest).read_text()),json.loads(Path(a.machine_json).read_text()));dump(report,a.output)
        if report['status']!='passed':raise SystemExit(2)
    else:
        env=discover(a.binary,a.profiles)
        if a.cmd=='env':dump(env)
        elif a.cmd=='profiles':dump(write_configs(env,a))
        elif a.cmd=='slice':
            r=slice_job(env,a.config_dir,a.models,a.output,a.bed,not a.keep_placement)
            dump({k:v for k,v in r.items() if k not in ['project_settings','metadata','gcode_headers']})

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,FileNotFoundError,FileExistsError,ImportError,subprocess.TimeoutExpired) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(1)
