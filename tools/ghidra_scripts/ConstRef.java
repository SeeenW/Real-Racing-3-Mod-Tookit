// 找出把某个立即数（默认 0x3248）当偏移使用的指令，并列出所属函数。
// 用法: ConstRef.java <out.txt> <hexconst>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.OperandType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.PrintWriter;

public class ConstRef extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args.length > 0 ? args[0] : "constref.txt";
        long want = args.length > 1 ? Long.parseLong(args[1].replace("0x", ""), 16) : 0x3248L;
        PrintWriter w = new PrintWriter(out, "UTF-8");
        w.println("CONST 0x" + Long.toHexString(want));
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        int hits = 0;
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction ins = it.next();
            boolean hit = false;
            for (int i = 0; i < ins.getNumOperands(); i++) {
                if (ins.getOperandType(i) == OperandType.SCALAR) {
                    Object[] objs = ins.getOpObjects(i);
                    for (Object o : objs) {
                        if (o instanceof ghidra.program.model.scalar.Scalar) {
                            long v = ((ghidra.program.model.scalar.Scalar) o).getUnsignedValue();
                            if (v == want) { hit = true; }
                        }
                    }
                }
            }
            if (hit) {
                Address a = ins.getAddress();
                Function f = getFunctionContaining(a);
                w.println(String.format("  0x%s  %s  %s", a, ins.toString(),
                        f == null ? "<no fn>" : f.getName() + " @0x" + f.getEntryPoint()));
                hits++;
            }
        }
        w.println("hits=" + hits);
        w.close();
        println("wrote " + out + " hits=" + hits);
    }
}
