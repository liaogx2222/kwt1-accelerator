// Generated solely from fixed ABI metadata and packet headers.
localparam integer CB_CTX_M=0;
localparam integer CB_CTX_S=1;
localparam integer CB_FC1_B=2;
localparam integer CB_FC1_M=258;
localparam integer CB_FC1_S=514;
localparam integer CB_FC2_B=770;
localparam integer CB_FC2_M=834;
localparam integer CB_FC2_S=898;
localparam integer CB_K_M=962;
localparam integer CB_K_S=1026;
localparam integer CB_LN1_B=1090;
localparam integer CB_LN1_EPS=1154;
localparam integer CB_LN1_G=1156;
localparam integer CB_LN1_M=1220;
localparam integer CB_LN1_S=1221;
localparam integer CB_LN2_B=1222;
localparam integer CB_LN2_EPS=1286;
localparam integer CB_LN2_G=1288;
localparam integer CB_LN2_M=1352;
localparam integer CB_LN2_S=1353;
localparam integer CB_O_B=1354;
localparam integer CB_O_M=1418;
localparam integer CB_O_S=1482;
localparam integer CB_Q_M=1546;
localparam integer CB_Q_S=1610;
localparam integer CB_R1_COEFF=1674;
localparam integer CB_R2_COEFF=1680;
localparam integer CB_SCORE_M=1686;
localparam integer CB_SCORE_S=1687;
localparam integer CB_V_M=1688;
localparam integer CB_V_S=1752;
localparam integer WB_Q=0;
localparam integer WB_K=256;
localparam integer WB_V=512;
localparam integer WB_O=768;
localparam integer WB_FC1=1024;
localparam integer WB_FC2=2048;
function automatic [31:0] profile_header(input integer common_flag,input integer lid,input integer index);
begin
 if(common_flag)case(index)
0:profile_header=32'h3854574b;
1:profile_header=32'h00544b50;
2:profile_header=32'hff000001;
3:profile_header=32'h00000001;
4:profile_header=32'h00000080;
5:profile_header=32'h00004000;
6:profile_header=32'h2c64909b;
7:profile_header=32'h107d23a9;
8:profile_header=32'h6972ba8f;
9:profile_header=32'h7ffa6a30;
10:profile_header=32'he88362ec;
11:profile_header=32'h1b833387;
12:profile_header=32'h6f10069e;
13:profile_header=32'h2d6cd823;
14:profile_header=32'h1d17eaf0;
15:profile_header=32'hf99bcf14;
default:profile_header=0;endcase
 else case(lid*16+index)
0:profile_header=32'h3854574b;
1:profile_header=32'h00544b50;
2:profile_header=32'h00010001;
3:profile_header=32'h00000026;
4:profile_header=32'h00001300;
5:profile_header=32'h0000dde0;
6:profile_header=32'h2c64909b;
7:profile_header=32'h107d23a9;
8:profile_header=32'h6972ba8f;
9:profile_header=32'h7ffa6a30;
10:profile_header=32'he88362ec;
11:profile_header=32'h1b833387;
12:profile_header=32'h6f10069e;
13:profile_header=32'h2d6cd823;
14:profile_header=32'h56bd983b;
15:profile_header=32'h7e453038;
16:profile_header=32'h3854574b;
17:profile_header=32'h00544b50;
18:profile_header=32'h01010001;
19:profile_header=32'h00000026;
20:profile_header=32'h00001300;
21:profile_header=32'h0000dde0;
22:profile_header=32'h2c64909b;
23:profile_header=32'h107d23a9;
24:profile_header=32'h6972ba8f;
25:profile_header=32'h7ffa6a30;
26:profile_header=32'he88362ec;
27:profile_header=32'h1b833387;
28:profile_header=32'h6f10069e;
29:profile_header=32'h2d6cd823;
30:profile_header=32'hbd3bb88b;
31:profile_header=32'h8e23136c;
32:profile_header=32'h3854574b;
33:profile_header=32'h00544b50;
34:profile_header=32'h02010001;
35:profile_header=32'h00000026;
36:profile_header=32'h00001300;
37:profile_header=32'h0000dde0;
38:profile_header=32'h2c64909b;
39:profile_header=32'h107d23a9;
40:profile_header=32'h6972ba8f;
41:profile_header=32'h7ffa6a30;
42:profile_header=32'he88362ec;
43:profile_header=32'h1b833387;
44:profile_header=32'h6f10069e;
45:profile_header=32'h2d6cd823;
46:profile_header=32'hd142f9bc;
47:profile_header=32'h62e7ac3b;
48:profile_header=32'h3854574b;
49:profile_header=32'h00544b50;
50:profile_header=32'h03010001;
51:profile_header=32'h00000026;
52:profile_header=32'h00001300;
53:profile_header=32'h0000dde0;
54:profile_header=32'h2c64909b;
55:profile_header=32'h107d23a9;
56:profile_header=32'h6972ba8f;
57:profile_header=32'h7ffa6a30;
58:profile_header=32'he88362ec;
59:profile_header=32'h1b833387;
60:profile_header=32'h6f10069e;
61:profile_header=32'h2d6cd823;
62:profile_header=32'h72581221;
63:profile_header=32'hf8d08d99;
64:profile_header=32'h3854574b;
65:profile_header=32'h00544b50;
66:profile_header=32'h04010001;
67:profile_header=32'h00000026;
68:profile_header=32'h00001300;
69:profile_header=32'h0000dde0;
70:profile_header=32'h2c64909b;
71:profile_header=32'h107d23a9;
72:profile_header=32'h6972ba8f;
73:profile_header=32'h7ffa6a30;
74:profile_header=32'he88362ec;
75:profile_header=32'h1b833387;
76:profile_header=32'h6f10069e;
77:profile_header=32'h2d6cd823;
78:profile_header=32'h4f47649d;
79:profile_header=32'h7050eb2d;
80:profile_header=32'h3854574b;
81:profile_header=32'h00544b50;
82:profile_header=32'h05010001;
83:profile_header=32'h00000026;
84:profile_header=32'h00001300;
85:profile_header=32'h0000dde0;
86:profile_header=32'h2c64909b;
87:profile_header=32'h107d23a9;
88:profile_header=32'h6972ba8f;
89:profile_header=32'h7ffa6a30;
90:profile_header=32'he88362ec;
91:profile_header=32'h1b833387;
92:profile_header=32'h6f10069e;
93:profile_header=32'h2d6cd823;
94:profile_header=32'h879cc9a0;
95:profile_header=32'hdb9a7c27;
96:profile_header=32'h3854574b;
97:profile_header=32'h00544b50;
98:profile_header=32'h06010001;
99:profile_header=32'h00000026;
100:profile_header=32'h00001300;
101:profile_header=32'h0000dde0;
102:profile_header=32'h2c64909b;
103:profile_header=32'h107d23a9;
104:profile_header=32'h6972ba8f;
105:profile_header=32'h7ffa6a30;
106:profile_header=32'he88362ec;
107:profile_header=32'h1b833387;
108:profile_header=32'h6f10069e;
109:profile_header=32'h2d6cd823;
110:profile_header=32'h9c5c55aa;
111:profile_header=32'h4b28b401;
112:profile_header=32'h3854574b;
113:profile_header=32'h00544b50;
114:profile_header=32'h07010001;
115:profile_header=32'h00000026;
116:profile_header=32'h00001300;
117:profile_header=32'h0000dde0;
118:profile_header=32'h2c64909b;
119:profile_header=32'h107d23a9;
120:profile_header=32'h6972ba8f;
121:profile_header=32'h7ffa6a30;
122:profile_header=32'he88362ec;
123:profile_header=32'h1b833387;
124:profile_header=32'h6f10069e;
125:profile_header=32'h2d6cd823;
126:profile_header=32'h3b5203fe;
127:profile_header=32'h3e1f4a20;
128:profile_header=32'h3854574b;
129:profile_header=32'h00544b50;
130:profile_header=32'h08010001;
131:profile_header=32'h00000026;
132:profile_header=32'h00001300;
133:profile_header=32'h0000dde0;
134:profile_header=32'h2c64909b;
135:profile_header=32'h107d23a9;
136:profile_header=32'h6972ba8f;
137:profile_header=32'h7ffa6a30;
138:profile_header=32'he88362ec;
139:profile_header=32'h1b833387;
140:profile_header=32'h6f10069e;
141:profile_header=32'h2d6cd823;
142:profile_header=32'h337eb6a1;
143:profile_header=32'he2832656;
144:profile_header=32'h3854574b;
145:profile_header=32'h00544b50;
146:profile_header=32'h09010001;
147:profile_header=32'h00000026;
148:profile_header=32'h00001300;
149:profile_header=32'h0000dde0;
150:profile_header=32'h2c64909b;
151:profile_header=32'h107d23a9;
152:profile_header=32'h6972ba8f;
153:profile_header=32'h7ffa6a30;
154:profile_header=32'he88362ec;
155:profile_header=32'h1b833387;
156:profile_header=32'h6f10069e;
157:profile_header=32'h2d6cd823;
158:profile_header=32'h35d4d7f1;
159:profile_header=32'h524856a6;
160:profile_header=32'h3854574b;
161:profile_header=32'h00544b50;
162:profile_header=32'h0a010001;
163:profile_header=32'h00000026;
164:profile_header=32'h00001300;
165:profile_header=32'h0000dde0;
166:profile_header=32'h2c64909b;
167:profile_header=32'h107d23a9;
168:profile_header=32'h6972ba8f;
169:profile_header=32'h7ffa6a30;
170:profile_header=32'he88362ec;
171:profile_header=32'h1b833387;
172:profile_header=32'h6f10069e;
173:profile_header=32'h2d6cd823;
174:profile_header=32'ha4654103;
175:profile_header=32'hb7f60797;
176:profile_header=32'h3854574b;
177:profile_header=32'h00544b50;
178:profile_header=32'h0b010001;
179:profile_header=32'h00000026;
180:profile_header=32'h00001300;
181:profile_header=32'h0000dde0;
182:profile_header=32'h2c64909b;
183:profile_header=32'h107d23a9;
184:profile_header=32'h6972ba8f;
185:profile_header=32'h7ffa6a30;
186:profile_header=32'he88362ec;
187:profile_header=32'h1b833387;
188:profile_header=32'h6f10069e;
189:profile_header=32'h2d6cd823;
190:profile_header=32'h1adbc7cb;
191:profile_header=32'h387094e2;
default:profile_header=0;endcase
end
endfunction
function automatic [17:0] packet_location_legacy(input integer common_flag,input integer byte_position,input integer halfword);
integer pos,logical_address,logical_bank;begin
packet_location_legacy=0;pos=byte_position;logical_address=0;logical_bank=0;
if(common_flag)begin
if(pos>=192 && pos<16576)begin
logical_bank=18+halfword;logical_address=(pos-192)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
end
else begin
if(pos>=4928 && pos<4932)begin
logical_bank=16+halfword;logical_address=0+(pos-4928)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=4944 && pos<4948)begin
logical_bank=16+halfword;logical_address=1+(pos-4944)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=4960 && pos<5984)begin
logical_bank=16+halfword;logical_address=2+(pos-4960)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=5984 && pos<7008)begin
logical_bank=16+halfword;logical_address=258+(pos-5984)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=7008 && pos<8032)begin
logical_bank=16+halfword;logical_address=514+(pos-7008)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=8032 && pos<24416)begin
logical_address=2048+((pos-8032)%4096)/2+halfword;logical_bank=2*((pos-8032)/4096)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=24416 && pos<24672)begin
logical_bank=16+halfword;logical_address=770+(pos-24416)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=24672 && pos<24928)begin
logical_bank=16+halfword;logical_address=834+(pos-24672)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=24928 && pos<25184)begin
logical_bank=16+halfword;logical_address=898+(pos-24928)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=25184 && pos<41568)begin
logical_address=4096+((pos-25184)%4096)/2+halfword;logical_bank=2*((pos-25184)/4096)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=41568 && pos<41824)begin
logical_bank=16;logical_address=1880+(pos-41568)/2+halfword;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=41824 && pos<42080)begin
logical_bank=16+halfword;logical_address=962+(pos-41824)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=42080 && pos<42336)begin
logical_bank=16+halfword;logical_address=1026+(pos-42080)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=42336 && pos<46432)begin
logical_address=512+((pos-42336)%1024)/2+halfword;logical_bank=2*((pos-42336)/1024)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46432 && pos<46688)begin
logical_bank=16+halfword;logical_address=1090+(pos-46432)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46688 && pos<46696)begin
logical_bank=16+halfword;logical_address=1154+(pos-46688)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46704 && pos<46960)begin
logical_bank=16+halfword;logical_address=1156+(pos-46704)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46960 && pos<46964)begin
logical_bank=16+halfword;logical_address=1220+(pos-46960)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46976 && pos<46980)begin
logical_bank=16+halfword;logical_address=1221+(pos-46976)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=46992 && pos<47248)begin
logical_bank=16+halfword;logical_address=1222+(pos-46992)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47248 && pos<47256)begin
logical_bank=16+halfword;logical_address=1286+(pos-47248)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47264 && pos<47520)begin
logical_bank=16+halfword;logical_address=1288+(pos-47264)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47520 && pos<47524)begin
logical_bank=16+halfword;logical_address=1352+(pos-47520)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47536 && pos<47540)begin
logical_bank=16+halfword;logical_address=1353+(pos-47536)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47552 && pos<47808)begin
logical_bank=16+halfword;logical_address=1354+(pos-47552)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=47808 && pos<48064)begin
logical_bank=16+halfword;logical_address=1418+(pos-47808)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=48064 && pos<48320)begin
logical_bank=16+halfword;logical_address=1482+(pos-48064)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=48320 && pos<52416)begin
logical_address=1536+((pos-48320)%1024)/2+halfword;logical_bank=2*((pos-48320)/1024)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=52416 && pos<52672)begin
logical_bank=16+halfword;logical_address=1546+(pos-52416)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=52672 && pos<52928)begin
logical_bank=16+halfword;logical_address=1610+(pos-52672)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=52928 && pos<57024)begin
logical_address=0+((pos-52928)%1024)/2+halfword;logical_bank=2*((pos-52928)/1024)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57024 && pos<57048)begin
logical_bank=16+halfword;logical_address=1674+(pos-57024)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57056 && pos<57080)begin
logical_bank=16+halfword;logical_address=1680+(pos-57056)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57088 && pos<57092)begin
logical_bank=16+halfword;logical_address=1686+(pos-57088)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57104 && pos<57108)begin
logical_bank=16+halfword;logical_address=1687+(pos-57104)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57120 && pos<57376)begin
logical_bank=16+halfword;logical_address=1688+(pos-57120)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57376 && pos<57632)begin
logical_bank=16+halfword;logical_address=1752+(pos-57376)/4;
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
if(pos>=57632 && pos<61728)begin
logical_address=1024+((pos-57632)%1024)/2+halfword;logical_bank=2*((pos-57632)/1024)+(logical_address/4096);
packet_location_legacy={1'b1,logical_bank[4:0],logical_address[11:0]};end
end
end endfunction

// Repack original canonical weights for sixteen-column reads across banks0..7.
// No packet/CRC/parameter byte changes. All arithmetic here is bit selection.
function automatic [17:0] packet_location(input integer common_flag,input integer pos,input integer halfword);
 reg [17:0] old;reg [12:0] u;reg [4:0] bank;reg [11:0] address;
 begin
  old=packet_location_legacy(common_flag,pos,halfword);packet_location=old;
  if(old[17]&&old[16:12]<8)begin
   u={old[12],old[11:0]};
   bank={3'd0,old[14:13]}+(u[12]?(u[8]?5'd4:5'd0):(u[6]?5'd4:5'd0));
   address=u[12]?(12'd2048+{2'd0,u[10:9],u[7:0]}):{1'b0,u[11:7],u[5:0]};
   packet_location={1'b1,bank,address};
  end
 end
endfunction
