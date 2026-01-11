module redundant_demo ( a, b, y, z );
  input a, b;
  output y, z;
  wire w1, w2;

  assign w1 = a & b;
  assign w2 = b & a;

  assign y = w1;
  assign z = w2;
endmodule
