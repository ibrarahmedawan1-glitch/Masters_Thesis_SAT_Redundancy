module redundant_9 (input a, input b, input c, output y, output z);
  wire w1, w2;
  assign w1 = (a & b) & c;
  assign w2 = (a & b) & c;
  assign y = w1;
  assign z = w2;
endmodule
