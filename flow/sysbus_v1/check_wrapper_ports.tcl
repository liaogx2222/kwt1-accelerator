# Synopsys collections can represent a bus as one aggregate or as bit ports.
# The HDL's fixed bus declarations are source-hash checked before this gate.
proc sysbus_require_port {port width} {
 set pins [get_ports -quiet ${port}*]
 set count [sizeof_collection $pins]
 set names [get_object_name $pins]
 if {$count == 1 && [lindex $names 0] eq $port} {
  puts "SYSBUS_PORT_VERIFIED $port width=$width representation=aggregate"
  return
 }
 if {$count != $width} {error "System Bus port width mismatch $port expected=$width count=$count names=$names"}
 if {$width == 1} {error "System Bus scalar name mismatch $port names=$names"}
 for {set bit 0} {$bit < $width} {incr bit} {
  set expected [format {%s[%d]} $port $bit]
  if {[lsearch -exact $names $expected] < 0} {error "System Bus bus bit missing $expected names=$names"}
 }
 puts "SYSBUS_PORT_VERIFIED $port width=$width representation=bits"
}
