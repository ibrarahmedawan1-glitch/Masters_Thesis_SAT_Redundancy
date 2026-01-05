module arbiter_8bit (
    input [7:0] req,    // 8 devices requesting access
    output reg [7:0] gnt // Grant signal (One-Hot encoded)
);

    // Priority Logic: Lower bit index = Higher Priority
    // This creates a "daisy chain" structure in gates
    always @(*) begin
        gnt = 8'b00000000; // Default: no grant
        
        if (req[0])      gnt[0] = 1'b1;
        else if (req[1]) gnt[1] = 1'b1;
        else if (req[2]) gnt[2] = 1'b1;
        else if (req[3]) gnt[3] = 1'b1;
        else if (req[4]) gnt[4] = 1'b1;
        else if (req[5]) gnt[5] = 1'b1;
        else if (req[6]) gnt[6] = 1'b1;
        else if (req[7]) gnt[7] = 1'b1;
    end

endmodule