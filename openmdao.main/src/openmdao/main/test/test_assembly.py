# pylint: disable-msg=C0111,C0103

import os
import shutil
import unittest
import sys

from openmdao.main.api import Assembly, Component, Driver, set_as_top, SimulationRoot
from openmdao.main.datatypes.api import Float, Str, Slot, List
from openmdao.util.decorators import add_delegate
from openmdao.main.hasobjective import HasObjective


class Multiplier(Component):
    rval_in = Float(iotype='in')
    rval_out = Float(iotype='out')
    mult = Float(iotype='in')
    
    def __init__(self):
        super(Multiplier, self).__init__()
        self.rval_in = 4.
        self.rval_out = 7.
        self.mult = 1.5

    def execute(self):
        self.rval_out = self.rval_in * self.mult
        

class Simple(Component):
    
    a = Float(iotype='in')
    b = Float(iotype='in')
    c = Float(iotype='out')
    d = Float(iotype='out')
    
    def __init__(self):
        super(Simple, self).__init__()
        self.a = 4.
        self.b = 5.
        self.c = 7.
        self.d = 1.5

    def execute(self):
        self.c = self.a + self.b
        self.d = self.a - self.b


class DummyComp(Component):
    
    r = Float(iotype='in')
    r2 = Float(iotype='in')
    r3 = Float(iotype='in',desc="some random variable",low=-1.0,high=1.0,other_meta_data="test")
    s = Str(iotype='in')
    rout = Float(iotype='out', units='ft')
    r2out = Float(iotype='out')
    sout = Str(iotype='out')
    slistout = List(Str, iotype='out')
    
    dummy_in = Slot(Component, iotype='in')
    dummy_out = Slot(Component, iotype='out')
    dummy_out_no_copy = Slot(Component, iotype='out', copy=None)
    
    def __init__(self):
        super(DummyComp, self).__init__()
        self.r = 1.0
        self.r2 = -1.0
        self.rout = 0.0
        self.r2out = 0.0
        self.s = 'a string'
        self.sout = ''
        
        # make a nested container with input and output ContainerVars
        self.add('dummy', Multiplier())
        self.dummy_in = self.dummy
        self.dummy_out = self.dummy
                
    def execute(self):
        self.rout = self.r * 1.5
        self.r2out = self.r2 + 10.0
        self.sout = self.s[::-1]
        # pylint: disable-msg=E1101
        self.dummy.execute()


class Wrapper(Assembly):
    """
    Define a single-component Assembly so we explicitly control
    what variables are visible via passthrough traits.
    """

    def __init__(self):
        super(Wrapper, self).__init__()
        self.add('comp', Comp())
        self.driver.workflow.add('comp')

    def tree_rooted(self):
        """ Defines passthrough conections once NPSS has loaded. """
        super(Wrapper, self).tree_rooted()
        for path in ('x', 'y', 'z'):
            val = self.get('comp.'+path)
            self.create_passthrough('comp.'+path)

    def run(self):
        self._logger.debug('Wrapper.run() %r %r (%r %r)',
                           self.x, self.y, self.comp.x, self.comp.y)
        super(Wrapper, self).run()
        self._logger.debug('    complete')
        self._logger.debug('        %r (%r)', self.z, self.comp.z)


class FloatProxy(Float):
    """
    Example of a 'proxy' trait. Normally variables in the `_vals` dictionary
    here would actually be somewhere else in a wrapped code.
    """

    def __init__(self, **metadata):
        self._vals = {}
        Float.__init__(self, **metadata)
        self._metadata['type'] = 'property'  # Just to show correct type.

    def get(self, obj, name):
        return self._vals.get(id(obj), {}).get(name, 0.)

    def set(self, obj, name, value):
        if id(obj) not in self._vals:
            self._vals[id(obj)] = {}
        self._vals[id(obj)][name] = value


class Comp(Component):

    x = FloatProxy(iotype='in')
    y = FloatProxy(iotype='in')
    z = FloatProxy(iotype='out')

    def execute(self):
        self._logger.debug('execute')
        self._logger.debug('    %r %r', self.x, self.y)
        self.z = self.x * self.y
        self._logger.debug('    done')


class AssemblyTestCase(unittest.TestCase):

    def setUp(self):
        """
        top
            comp1
            nested
                comp1
            comp2
            comp3
        """
        SimulationRoot.chroot(os.getcwd())
        top = self.asm = set_as_top(Assembly())
        top.add('comp1', DummyComp())
        nested = top.add('nested', Assembly())
        nested.add('comp1', DummyComp())
        for name in ['comp2', 'comp3']:
            top.add(name, DummyComp())
            
        top.driver.workflow.add(['comp1','nested','comp2','comp3'])
        nested.driver.workflow.add('comp1')
                
    def test_lazy_eval(self):
        top = set_as_top(Assembly())
        comp1 = top.add('comp1', Multiplier())
        comp2 = top.add('comp2', Multiplier())
        
        top.driver.workflow.add(['comp1', 'comp2'])
        
        top.comp1.mult = 2.0
        top.comp2.mult = 4.0
        top.connect('comp1.rval_out', 'comp2.rval_in')
        top.comp1.rval_in = 5.0
        top.run()
        self.assertEqual(top.get('comp1.rval_out'), 10.)
        self.assertEqual(top.get('comp2.rval_in'), 10.)
        self.assertEqual(top.get('comp2.rval_out'), 40.)
        self.assertEqual(top.comp1.exec_count, 1)
        self.assertEqual(top.comp2.exec_count, 1)
        
        # now change an input (mult) on comp2. This should only 
        # cause comp2 to execute when we run next time.
        top.set('comp2.mult', 3.0)
        top.run()
        self.assertEqual(top.get('comp1.rval_out'), 10.)
        self.assertEqual(top.get('comp2.rval_in'), 10.)
        self.assertEqual(top.get('comp2.rval_out'), 30.)
        self.assertEqual(top.comp1.exec_count, 1)
        self.assertEqual(top.comp2.exec_count, 2)
        
     
    def test_data_passing(self):
        comp1 = self.asm.comp1
        comp2 = self.asm.comp2
        self.asm.connect('comp1.rout','comp2.r')
        self.asm.connect('comp1.sout','comp2.s')
        self.asm.comp1.r = 3.0
        self.asm.comp1.s = 'once upon a time'
        self.assertEqual(comp1.get('r'), 3.0)
        self.assertEqual(comp1.get('s'), 'once upon a time')
        self.assertEqual(comp1.r, 3.0)
        self.assertEqual(comp1.s, 'once upon a time')
        
        # also, test that we can't do a direct set of a connected input
        # This tests Requirement Ticket #274
        oldval = self.asm.comp2.r
        try:
            self.asm.comp2.r = 44
        except Exception, err:
            self.assertEqual(str(err), "comp2: 'r' is already connected to source 'parent.comp1.rout'"+
                                       " and cannot be directly set")
        else:
            self.fail("Expected an Exception when setting a connected input")
        
        # verify that old value of connected input hasn't changed
        self.assertEqual(oldval, self.asm.comp2.r)
        
        self.asm.run()
        
        self.assertEqual(comp1.get('rout'), 4.5)
        self.assertEqual(comp1.get('sout'), 'emit a nopu ecno')
        self.assertEqual(comp1.rout, 4.5)
        self.assertEqual(comp1.sout, 'emit a nopu ecno')
        self.assertEqual(comp2.get('r'), 4.5)
        self.assertEqual(comp2.get('rout'), 6.75)
        self.assertEqual(comp2.r, 4.5)
        self.assertEqual(comp2.rout, 6.75)
        self.assertEqual(comp2.s, 'emit a nopu ecno')
        self.assertEqual(comp2.sout, 'once upon a time')
        
        # now test removal of the error callback when a connected input is disconnected
        self.asm.disconnect('comp1.rout','comp2.r')
        self.asm.comp2.r = 33
        self.assertEqual(33, self.asm.comp2.r)
        
    def test_direct_set_of_connected_input(self):
        comp1 = self.asm.comp1
        comp2 = self.asm.comp2
        self.asm.connect('comp1.rout','comp2.r')
        self.asm.connect('comp1.sout','comp2.s')
        
        # test that we can't do a direct set of a connected input
        oldval = self.asm.comp2.r
        try:
            self.asm.comp2.r = 44
        except Exception, err:
            self.assertEqual(str(err), "comp2: 'r' is already connected to source 'parent.comp1.rout'"+
                                       " and cannot be directly set")
        else:
            self.fail("Expected an Exception when setting a connected input")
        
        # verify that old value of connected input hasn't changed
        self.assertEqual(oldval, self.asm.comp2.r)
        
        # now test removal of the error callback when a connected input is disconnected
        self.asm.disconnect('comp1.rout','comp2.r')
        self.asm.comp2.r = 33
        self.assertEqual(33, self.asm.comp2.r)

    def test_connect_containers(self):
        self.asm.set('comp1.dummy_in.rval_in', 75.4)
        self.asm.connect('comp1.dummy_out','comp2.dummy_in')
        self.asm.connect('comp1.dummy_out_no_copy', 'comp3.dummy_in')
        self.asm.run()
        self.assertEqual(self.asm.get('comp2.dummy_in.rval_in'), 75.4)
        self.assertEqual(self.asm.get('comp2.dummy_in.rval_out'), 75.4*1.5)
        self.assertFalse(self.asm.comp1.dummy_out is self.asm.comp2.dummy_in)
        self.assertTrue(self.asm.comp1.dummy_out_no_copy is self.asm.comp3.dummy_in)
        
    def test_create_passthrough(self):
        self.asm.set('comp3.r', 75.4)
        self.asm.create_passthrough('comp3.rout')
        self.assertEqual(self.asm.comp3.r, 75.4)
        self.assertEqual(self.asm.rout, 0.0)
        self.asm.run()
        self.assertEqual(self.asm.comp3.rout, 75.4*1.5)
        self.assertEqual(self.asm.rout, 75.4*1.5)
        
        self.asm.create_passthrough('comp3.r3')
        metadata = self.asm.get_metadata('r3')
        self.assertEqual(metadata['iotype'],'in')
        self.assertEqual(metadata['desc'],'some random variable')
        self.assertEqual(metadata['low'],-1.0)
        self.assertEqual(metadata['high'],1.0)
        self.assertEqual(metadata['other_meta_data'],'test')
        
    def test_create_passthrough_already_exists(self):
        self.asm.create_passthrough('comp3.rout')
        try:
            self.asm.create_passthrough('comp3.rout')
        except Exception, err:
            # for some reason, KeyError turns 'rout' into \'rout\', so
            # test against str(KeyError(msg)) instead of just msg  :(
            self.assertEqual(str(err), str(KeyError(": 'rout' already exists")))
        else:
            self.fail('expected Exception')
        
    def test_autopassthrough_nested(self):
        self.asm.set('comp1.r', 8.)
        self.asm.connect('comp1.rout', 'nested.comp1.r')
        self.asm.connect('nested.comp1.rout','comp2.r')
        self.asm.run()
        self.assertEqual(self.asm.get('comp1.rout'), 12.)
        self.assertEqual(self.asm.get('comp2.rout'), 27.)
                
    def test_create_passthrough_alias(self):
        self.asm.nested.set('comp1.r', 75.4)
        self.asm.nested.create_passthrough('comp1.r','foobar')
        self.assertEqual(self.asm.nested.get('foobar'), 75.4)
        self.asm.run()
        self.assertEqual(self.asm.nested.get('foobar'), 75.4)
        
    def test_passthrough_already_connected(self):
        self.asm.connect('comp1.rout','comp2.r')
        self.asm.connect('comp1.sout','comp2.s')
        # this should fail since we're creating a second connection
        # to an input
        try:
            self.asm.create_passthrough('comp2.r')
        except RuntimeError, err:
            self.assertEqual(str(err), ": 'comp2.r' is already connected to source 'comp1.rout'")
        else:
            self.fail('RuntimeError expected')
        self.asm.set('comp1.s', 'some new string')
        # this one should be OK since outputs can have multiple connections
        self.asm.create_passthrough('comp1.sout')
        self.asm.run()
        self.assertEqual(self.asm.get('sout'), 'some new string'[::-1])
        
    def test_container_passthrough(self):
        self.asm.set('comp1.dummy_out.rval_in', 75.4)
        self.asm.create_passthrough('comp1.dummy_out','dummy_out_passthrough')
        self.asm.run()
        self.assertEqual(self.asm.get('dummy_out_passthrough.rval_out'), 75.4*1.5)

#    def test_discon_reconnect_passthrough(self):
#        self.fail('unfinished test')
        
    def test_invalid_connect(self):
        try:
            self.asm.connect('comp1.rout','comp2.rout')
        except RuntimeError, err:
            self.assertEqual('comp2: rout must be an input variable',
                             str(err))
        else:
            self.fail('exception expected')
        try:
            self.asm.connect('comp1.r','comp2.rout')
        except RuntimeError, err:
            self.assertEqual('comp1: r must be an output variable',
                             str(err))
        else:
            self.fail('RuntimeError expected')
            
    def test_self_connect(self):
        try:
            self.asm.connect('comp1.rout','comp1.r')
        except Exception, err:
            self.assertEqual(': Cannot connect comp1.rout to comp1.r. Both are on same component.',
                             str(err))
        else:
            self.fail('exception expected')
     
    def test_metadata_link(self):
        try:
            self.asm.connect('comp1.rout.units','comp2.s')
        except AttributeError, err:
            self.assertEqual(str(err), 
                    "comp1: Cannot locate variable named 'rout.units'")
        else:
            self.fail('NameError expected')
            
    def test_get_metadata(self):
        units = self.asm.comp1.get_metadata('rout', 'units')
        self.assertEqual(units, 'ft')
        
        meta = self.asm.comp1.get_metadata('rout')
        self.assertEqual(set(meta.keys()), 
                         set(['vartypename','units','high','iotype','type','low']))
        self.assertEqual(meta['vartypename'], 'Float')
        self.assertEqual(self.asm.comp1.get_metadata('slistout','vartypename'), 'List')
        
    def test_missing_metadata(self):
        foo = self.asm.comp1.get_metadata('rout', 'foo')
        self.assertEqual(foo, None)
        
        try:
            bar = self.asm.comp1.get_metadata('bogus', 'bar')
        except Exception as err:
            self.assertEqual(str(err), "comp1: Couldn't find metadata for trait bogus")
        else:
            self.fail("Exception expected")
            
    def test_circular_dependency(self):
        self.asm.connect('comp1.rout','comp2.r')
        try:
            self.asm.connect('comp2.rout','comp1.r')
        except Exception, err:
            self.assertEqual("circular dependency (['comp2', 'comp1']) would be created by"+
                             " connecting comp2.rout to comp1.r", str(err))
        else:
            self.fail('Exception expected')
            
    def test_disconnect(self):
        # first, run connected
        comp2 = self.asm.get('comp2')
        self.asm.connect('comp1.rout', 'comp2.r')
        self.asm.run()
        self.assertEqual(comp2.r, 1.5)
        self.asm.comp1.r = 3.0
        self.asm.run()
        self.assertEqual(comp2.r, 4.5)
        
        # now disconnect
        self.asm.comp1.r = 6.0
        self.asm.disconnect('comp2.r')
        self.asm.run()
        self.assertEqual(comp2.r, 4.5)
        
        # now reconnect
        self.asm.connect('comp1.rout','comp2.r')
        self.asm.run()
        self.assertEqual(comp2.r, 9.0)
        
    def test_input_passthrough_to_2_inputs(self):
        asm = set_as_top(Assembly())
        asm.add('nested', Assembly())
        comp1 = asm.nested.add('comp1', Simple())
        comp2 = asm.nested.add('comp2', Simple())
        
        asm.driver.workflow.add('nested')
        asm.nested.driver.workflow.add(['comp1','comp2'])
        
        asm.nested.create_passthrough('comp1.a') 
        asm.nested.connect('a', 'comp2.b') 
        self.assertEqual(asm.nested.comp1.a, 4.)
        self.assertEqual(asm.nested.comp2.b, 5.)
        asm.nested.a = 0.5
        # until we run, the values of comp1.a and comp2.b won't change
        self.assertEqual(asm.nested.comp1.a, 4.)
        self.assertEqual(asm.nested.comp2.b, 5.)
        self.assertEqual(asm.nested.comp2.get_valid(['b']), [False])
        self.assertEqual(asm.nested.get_valid(['comp2.b']), [False])
        asm.run()
        self.assertEqual(asm.nested.comp1.a, 0.5)
        self.assertEqual(asm.nested.comp2.b, 0.5)
        self.assertEqual(asm.nested.comp1.get_valid(['a']), [True])
        self.assertEqual(asm.nested.comp2.get_valid(['b']), [True])
        asm.nested.a = 999.
        self.assertEqual(asm.nested.comp1.get_valid(['a']), [False])
        self.assertEqual(asm.nested.comp2.get_valid(['b']), [False])
        self.assertEqual(asm.nested.comp1.a, 0.5)
        self.assertEqual(asm.nested.comp2.b, 0.5)
        asm.run()
        self.assertEqual(asm.nested.comp1.a, 999.)
        self.assertEqual(asm.nested.comp2.b, 999.)
        
    def test_connect_2_outs_to_passthrough(self):
        asm = set_as_top(Assembly())
        asm.add('nested', Assembly())
        asm.nested.add('comp1', Simple())
        asm.nested.add('comp2', Simple())
        asm.nested.create_passthrough('comp1.c')
        try:
            asm.nested.connect('comp2.d', 'c')
        except RuntimeError, err:
            self.assertEqual(str(err), "nested: 'c' is already connected to source 'comp1.c'")
        else:
            self.fail('RuntimeError expected')
        
 
    def test_discon_not_connected(self):
        self.asm.connect('comp1.rout','comp2.r')
        
        # disconnecting something that isn't connected is ok and shouldn't
        # raise an exception
        self.asm.disconnect('comp2.s')

    def test_listcon_with_deleted_objs(self):
        self.asm.add('comp3', DummyComp())
        self.asm.connect('comp1.rout', 'comp2.r')
        self.asm.connect('comp3.sout', 'comp2.s')
        conns = self.asm.list_connections()
        self.assertEqual(set(conns), set([('comp1.rout', 'comp2.r'),
                                 ('comp3.sout', 'comp2.s')]))
        self.asm.remove('comp3')
        conns = self.asm.list_connections()
        self.assertEqual(conns, [('comp1.rout', 'comp2.r')])
        self.asm.run()
        
            
    def test_assembly_connect_init(self):
        class MyComp(Component):
            ModulesInstallPath  = Str('', desc='', iotype='in')
            
            def execute(self):
                pass
            
            
        class MyAsm(Assembly):    
            ModulesInstallPath  = Str('C:/work/IMOO2/imoo/modules', desc='', iotype='in')
        
            def __init__(self):
                super(MyAsm, self).__init__()
                self.add('propulsion', MyComp())
                self.driver.workflow.add('propulsion')
                self.connect('ModulesInstallPath','propulsion.ModulesInstallPath')
        
        asm = set_as_top(MyAsm())
        asm.run()
        self.assertEqual(asm.ModulesInstallPath, 'C:/work/IMOO2/imoo/modules')
        self.assertEqual(asm.propulsion.ModulesInstallPath, 'C:/work/IMOO2/imoo/modules')

    def test_wrapper(self):
        # Test that wrapping via passthroughs to proxy traits works.
        top = set_as_top(Wrapper())

        expected = [
            '%s.FloatProxy' % __name__,
            'openmdao.main.datatypes.float.Float',
            'openmdao.main.variable.Variable',
            'enthought.traits.trait_handlers.TraitType',
            'enthought.traits.trait_handlers.BaseTraitHandler',
            '__builtin__.object'
        ]
        self.assertEqual(top.get_trait_typenames('x'), expected)

        for varname in ('x', 'comp.x', 'y', 'comp.y', 'z', 'comp.z'):
            self.assertEqual(top.get(varname), 0.)

        top.set('x', 6)
        top.set('y', 7)
        top.run()
        self.assertEqual(top.get('x'), 6.)
        self.assertEqual(top.get('comp.x'), 6.)
        self.assertEqual(top.get('y'), 7.)
        self.assertEqual(top.get('comp.y'), 7.)
        self.assertEqual(top.get('z'), 42.)
        self.assertEqual(top.get('comp.z'), 42.)

        egg_info = top.save_to_egg('Top', 'v1')
        try:
            egg = Component.load_from_eggfile(egg_info[0])
            self.assertEqual(egg.get('x'), 6.)
            self.assertEqual(egg.get('comp.x'), 6.)
            self.assertEqual(egg.get('y'), 7.)
            self.assertEqual(egg.get('comp.y'), 7.)
            self.assertEqual(egg.get('z'), 42.)
            self.assertEqual(egg.get('comp.z'), 42.)

            egg.set('x', 11)
            egg.set('y', 3)
            egg.run()
            self.assertEqual(egg.get('x'), 11.)
            self.assertEqual(egg.get('comp.x'), 11.)
            self.assertEqual(egg.get('y'), 3)
            self.assertEqual(egg.get('comp.y'), 3.)
            self.assertEqual(egg.get('z'), 33.)
            self.assertEqual(egg.get('comp.z'), 33.)
        finally:
            os.remove(egg_info[0])
            shutil.rmtree('Top')


if __name__ == "__main__":
    unittest.main()


