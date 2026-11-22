// Decompile the function that CONTAINS a given address, using an ARM64
// prologue scan to recover the real entry point (Ghidra's own function
// boundaries are unreliable in this stripped binary).
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//@category RR3

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;

public class Fn2 extends GhidraScript {

    /** STP x29, x30, [sp, #-imm]!  ->  0xA9807BFD masked by 0xFFE07FFF */
    private boolean isPrologue(int w) {
        return (w & 0xFFE07FFF) == 0xA9807BFD;
    }

    private int word(long addr) throws MemoryAccessException {
        return getInt(toAddr(addr));
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: Fn2.java <outfile> <hexaddr> [<hexaddr> ...]");
            return;
        }
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        try (PrintWriter pw = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", "").replace("0X", ""), 16);
                long entry = findEntry(v);
                pw.printf("### probe 0x%08X -> entry 0x%08X%n", v, entry);
                Address a = toAddr(entry);
                Function f = getFunctionAt(a);
                if (f == null) {
                    f = getFunctionContaining(a);
                }
                if (f == null) {
                    pw.println("NO FUNCTION");
                    continue;
                }
                dump(pw, dec, f, v);
            }
        }
        dec.dispose();
        println("wrote " + args[0]);
    }

    /** Scan backwards from addr for the nearest STP x29,x30,[sp,#-imm]! */
    private long findEntry(long addr) throws MemoryAccessException {
        long a = addr & ~3L;
        for (int k = 0; k < 3000; k++) {
            if (a < 0x988000L) {
                break;
            }
            if (isPrologue(word(a))) {
                return a;
            }
            a -= 4;
        }
        return addr;
    }

    private void dump(PrintWriter pw, DecompInterface dec, Function f, long probe) {
        pw.println("=".repeat(110));
        pw.printf("FUNCTION %s @0x%08X  size=%d  (probe 0x%08X)%n", f.getName(),
                f.getEntryPoint().getOffset(), f.getBody().getNumAddresses(), probe);
        pw.println("=".repeat(110));

        Set<Function> callers = f.getCallingFunctions(monitor);
        pw.println("CALLERS:");
        for (Function c : callers) {
            pw.printf("  %s @0x%08X%n", c.getName(), c.getEntryPoint().getOffset());
        }
        Set<Function> callees = f.getCalledFunctions(monitor);
        pw.println("CALLEES:");
        for (Function c : callees) {
            pw.printf("  %s @0x%08X%n", c.getName(), c.getEntryPoint().getOffset());
        }

        Set<String> strings = new LinkedHashSet<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            for (Reference r : ins.getReferencesFrom()) {
                Address t = r.getToAddress();
                if (t == null) {
                    continue;
                }
                Data d = getDataAt(t);
                if (d != null && d.hasStringValue()) {
                    strings.add(String.format("  0x%08X  %s", t.getOffset(),
                            d.getValue().toString().replace("\n", "\\n")));
                }
            }
        }
        if (!strings.isEmpty()) {
            pw.println("STRINGS:");
            for (String s : strings) {
                pw.println(s);
            }
        }

        DecompileResults res = dec.decompileFunction(f, 180, monitor);
        pw.println("DECOMPILED:");
        if (res != null && res.decompileCompleted()) {
            for (String ln : res.getDecompiledFunction().getC().split("\n")) {
                pw.println("  " + ln);
            }
        } else {
            pw.println("  <failed>");
        }
        pw.println();
    }
}
