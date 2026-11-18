// Algebraically equal, intentionally different gate structures. Qualifies SAT.
module sanity_gold(input [3:0] a,b,c,output [3:0] y);
 assign y=(a&b)|(a&c);
endmodule
module sanity_gate(input [3:0] a,b,c,output [3:0] y);
 assign y=a&(b|c);
endmodule
