module alu_8bit (
    input [7:0] A,
    input [7:0] B,
    input [2:0] Op,      // Operation Selector
    output reg [7:0] Out,
    output Zero          // Status Flag
);

    // This behavioral code will be synthesized into complex gate logic
    always @(*) begin
        case (Op)
            3'b000: Out = A + B;       // Addition
            3'b001: Out = A - B;       // Subtraction
            3'b010: Out = A & B;       // Bitwise AND
            3'b011: Out = A | B;       // Bitwise OR
            3'b100: Out = A ^ B;       // Bitwise XOR
            3'b101: Out = ~A;          // Inversion
            3'b110: Out = A << 1;      // Logical Shift Left
            3'b111: Out = A >> 1;      // Logical Shift Right
            default: Out = 8'b0;
        endcase
    end

    // Zero flag logic
    assign Zero = (Out == 8'b0);

endmodule