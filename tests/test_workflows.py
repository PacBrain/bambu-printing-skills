import importlib.util,json,pathlib,tempfile,unittest,zipfile
import numpy as np
import trimesh

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bambu',ROOT/'skills/bambu-printing/scripts/bambu.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
        for k in ['machine','process','filament']:(self.root/k).mkdir()
    def tearDown(self):self.tmp.cleanup()
    def put(self,name,**data):(self.root/'machine'/(name+'.json')).write_text(json.dumps({'name':name,**data}))
    def test_parent_include_and_child_precedence(self):
        self.put('parent',a=1,machine_end_gcode='parent');self.put('fragment',machine_end_gcode='fragment');self.put('child',inherits='parent',include=['fragment'],machine_end_gcode='child')
        d=b.Profiles(self.root).resolve('machine','child');self.assertEqual(d['a'],1);self.assertEqual(d['machine_end_gcode'],'child')
    def test_parameter_include_is_not_blindly_merged(self):
        self.put('fragment',a=2);self.put('child',include=['fragment'])
        with self.assertRaisesRegex(ValueError,'Unsupported parameter include'):b.Profiles(self.root).resolve('machine','child')
    def test_inherited_include_is_rejected(self):
        self.put('parent',a=2);self.put('fragment',inherits='parent',machine_end_gcode='M400');self.put('child',include=['fragment'])
        with self.assertRaisesRegex(ValueError,'Unsupported inherited'):b.Profiles(self.root).resolve('machine','child')
    def test_cycle_rejected(self):
        self.put('a',inherits='b');self.put('b',include=['a'])
        with self.assertRaisesRegex(ValueError,'cycle'):b.Profiles(self.root).resolve('machine','a')
    def test_missing_parent_rejected(self):
        self.put('a',inherits='absent')
        with self.assertRaisesRegex(ValueError,'Missing'):b.Profiles(self.root).resolve('machine','a')
    def test_vendor_gcode_preserved(self):
        self.put('fragment',machine_end_gcode='M400\nT65535\n');self.put('machine',include=['fragment'])
        self.assertEqual(b.Profiles(self.root).resolve('machine','machine')['machine_end_gcode'],'M400\nT65535\n')
    def test_user_override_diff_is_carried_for_gui_reopen(self):
        self.put('machine',nozzle_diameter=['0.4'])
        for kind,name,extra in [('process','process',{'wall_loops':'2'}),('filament','filament',{})]:
            (self.root/kind/(name+'.json')).write_text(json.dumps({'name':name,'compatible_printers':['machine'],**extra}))
        d,_=b.configs({'profiles':str(self.root)},'machine','process','filament',{'process':{'wall_loops':'3'}})
        self.assertEqual(d['process']['different_settings_to_system'],['wall_loops'])
        self.assertEqual(d['process']['inherits'],'process')
        with self.assertRaisesRegex(ValueError,'Deprecated'):
            b.configs({'profiles':str(self.root)},'machine','process','filament',{'process':{'only_one_wall_top':'0'}})

class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='with spaces 测试 ');self.root=pathlib.Path(self.tmp.name)
        self.path=self.root/'cube 左.stl';trimesh.creation.box(extents=[20,20,20]).export(self.path)
        self.machine={'printable_area':['0x0','100x0','100x100','0x100'],'printable_height':'100','bed_exclude_area':[], 'extruder_clearance_radius':'20','extruder_clearance_height_to_rod':'10'}
    def tearDown(self):self.tmp.cleanup()
    def job(self,x=50,y=50,units='mm'):
        return {'objects':[{'path':str(self.path),'units':units,'center_xy_mm':[x,y]}],'brim_width_mm':5,'brim_gap_mm':.1}
    def test_valid_with_spaces_unicode(self):self.assertEqual(b.preflight(self.job(),self.machine)['status'],'passed')
    def test_units_required(self):
        with self.assertRaisesRegex(ValueError,'units'):b.preflight(self.job(units=None),self.machine)
    def test_inches_converted_before_fit(self):self.assertEqual(b.preflight(self.job(units='inch'),self.machine)['status'],'failed')
    def test_brim_outside_rejected(self):self.assertEqual(b.preflight(self.job(x=12),self.machine)['status'],'failed')
    def test_keepout_rejected(self):
        self.machine['bed_exclude_area']=['45x45','55x45','55x55','45x55']
        self.assertEqual(b.preflight(self.job(),self.machine)['status'],'failed')
    def test_open_mesh_rejected(self):
        m=trimesh.creation.box();m.update_faces(np.arange(len(m.faces)-1));m.export(self.path)
        with self.assertRaisesRegex(ValueError,'closed volume'):b.mesh_info(self.path,'mm')
    def test_overlap_rejected(self):
        j=self.job();j['objects']*=2
        self.assertEqual(b.preflight(j,self.machine)['status'],'failed')
    def test_sequential_head_clearance(self):
        j=self.job(25,25);j['objects'].append({**j['objects'][0],'center_xy_mm':[75,75]});j['print_sequence']='by object'
        self.assertTrue(any('clearance' in x for x in b.preflight(j,self.machine)['errors']))

class ArchiveTest(unittest.TestCase):
    def test_sliced_plate_empty_model_stub_is_not_editable_geometry(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'plate.gcode.3mf'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('3D/3dmodel.model','<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources/><build/></model>')
                z.writestr('Metadata/plate_1.gcode','; total layer number: 1\nG1 X1 Y1 E1\n')
            report=b.inspect_3mf(p);self.assertFalse(report['has_model']);self.assertTrue(report['has_toolpaths'])
    def test_production_extension_transforms(self):
        ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';pn='http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'scene.3mf'
            main=f'<model xmlns="{ns}" xmlns:p="{pn}" unit="millimeter"><resources><object id="2"><components><component objectid="1" p:path="/3D/Objects/part.model" transform="1 0 0 0 1 0 0 0 1 10 0 0"/></components></object></resources><build><item objectid="2" transform="1 0 0 0 1 0 0 0 1 20 30 40"/></build></model>'
            part=f'<model xmlns="{ns}"><resources><object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="2" y="3" z="4"/><vertex x="1" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources></model>'
            with zipfile.ZipFile(p,'w') as z:z.writestr('3D/3dmodel.model',main);z.writestr('3D/Objects/part.model',part)
            r=b.inspect_3mf(p)
            self.assertEqual(r['build_objects'][0]['bounds_mm'],[[30,30,40],[32,33,44]])
            self.assertFalse(r['has_toolpaths'])
    def test_missing_executable(self):
        import unittest.mock
        with unittest.mock.patch('shutil.which',return_value=None),unittest.mock.patch('sys.platform','linux'),unittest.mock.patch.dict('os.environ',{},clear=True):
            with self.assertRaises(FileNotFoundError):b.discover('/does/not/exist')

if __name__=='__main__':unittest.main()
