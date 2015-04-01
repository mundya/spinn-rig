from rig.netlist import Net
class Vertex(object):'Represents an object that could be the source or sink of a net.';pass
class TestNet(object):
 def test_init_with_list(self):
  source=Vertex();sinks=[Vertex() for _ in range(3)];net=Net(source,sinks,.5);assert net.source is source;assert net.sinks is not sinks;assert net.sinks==sinks;assert net.weight==.5;assert source in net
  for sink in sinks:assert sink in net
  assert Vertex() not in net
 def test_init_with_object(self):source=Vertex();sink=Vertex();net=Net(source,sink,5);assert net.source is source;assert net.sinks==[sink];assert net.weight==5
