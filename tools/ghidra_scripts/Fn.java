// Decompile a single function body (no recursion), plus its callers, callees
// and every string referenced inside it. Small and fast.
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
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;

public class Fn extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: Fn.java <outfile> <hexaddr> [<hexaddr> ...]");
            return;
        }
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        try (PrintWriter pw = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", "").replace("0X", ""), 16);
                Address a = toAddr(v);
                Function f = getFunctionContaining(a);
                if (f == null) {
                    f = getFunctionAt(a);
                }
                if (f == null) {
                    pw.printf("NO FUNCTION at 0x%08X%n", v);
                    continue;
                }
                dump(pw, dec, f);
            }
        }
        dec.dispose();
        println("wrote " + args[0]);
    }

    private void dump(PrintWriter pw, DecompInterface dec, Function f) {
        pw.println("=".repeat(110));
        pw.printf("FUNCTION %s @0x%08X  size=%d%n", f.getName(),
                f.getEntryPoint().getOffset(), f.getBody().getNumAddresses());
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

        DecompileResults res = dec.decompileFunction(f, 120, monitor);
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
