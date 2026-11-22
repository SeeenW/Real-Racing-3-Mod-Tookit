// Decompile one or more functions by address, with callers/callees, and
// optionally every string referenced inside the decompiled body.
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//   ghidra_headless.bat <projdir> <proj> -process <lib> -noanalysis
//        -scriptPath tools\ghidra_scripts -postScript DumpFn.java <out> <addr>...
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
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class DumpFn extends GhidraScript {

    private static final int MAX_DEPTH = 2;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DumpFn.java <outfile> <hexaddr> [<hexaddr> ...]");
            return;
        }
        String outPath = args[0];

        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        List<Function> roots = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            long v = Long.parseLong(args[i].replace("0x", "").replace("0X", ""), 16);
            Address a = toAddr(v);
            Function f = getFunctionContaining(a);
            if (f == null) {
                f = getFunctionAt(a);
            }
            if (f == null) {
                println("no function at " + args[i]);
                continue;
            }
            roots.add(f);
        }

        try (PrintWriter pw = new PrintWriter(outPath, "UTF-8")) {
            Set<Long> seen = new LinkedHashSet<>();
            for (Function f : roots) {
                dumpFunction(pw, dec, f, 0, seen);
            }
        }
        dec.dispose();
        println("wrote " + outPath);
    }

    private void dumpFunction(PrintWriter pw, DecompInterface dec, Function f,
                              int depth, Set<Long> seen) {
        long key = f.getEntryPoint().getOffset();
        if (seen.contains(key)) {
            return;
        }
        seen.add(key);

        String pad = "  ".repeat(depth);
        pw.println("=".repeat(100));
        pw.printf("%sFUNCTION %s  @0x%08X  size=%d%n", pad, f.getName(),
                key, f.getBody().getNumAddresses());
        pw.println("=".repeat(100));

        // callers
        Set<Function> callers = f.getCallingFunctions(monitor);
        if (!callers.isEmpty()) {
            pw.println(pad + "CALLERS:");
            for (Function c : callers) {
                pw.printf("%s  - %s @0x%08X%n", pad, c.getName(), c.getEntryPoint().getOffset());
            }
        }
        // callees
        Set<Function> callees = f.getCalledFunctions(monitor);
        if (!callees.isEmpty()) {
            pw.println(pad + "CALLEES:");
            for (Function c : callees) {
                pw.printf("%s  - %s @0x%08X%n", pad, c.getName(), c.getEntryPoint().getOffset());
            }
        }

        // strings referenced from the body
        List<String> strings = new ArrayList<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            for (Reference r : ins.getReferencesFrom()) {
                Address t = r.getToAddress();
                if (t == null) {
                    continue;
                }
                var data = getDataAt(t);
                if (data != null && data.hasStringValue()) {
                    strings.add(String.format("    0x%08X  %s", t.getOffset(),
                            data.getValue().toString().replace("\n", "\\n")));
                }
            }
        }
        if (!strings.isEmpty()) {
            pw.println(pad + "STRINGS:");
            for (String s : strings) {
                pw.println(pad + s);
            }
        }

        // decompiled body
        DecompileResults res = dec.decompileFunction(f, 90, monitor);
        pw.println(pad + "DECOMPILED:");
        if (res != null && res.decompileCompleted()) {
            String[] lines = res.getDecompiledFunction().getC().split("\n");
            for (String ln : lines) {
                pw.println(pad + "  " + ln);
            }
        } else {
            pw.println(pad + "  <decompile failed>");
        }
        pw.println();

        if (depth < MAX_DEPTH) {
            for (Function c : callees) {
                dumpFunction(pw, dec, c, depth + 1, seen);
            }
        }
    }
}
