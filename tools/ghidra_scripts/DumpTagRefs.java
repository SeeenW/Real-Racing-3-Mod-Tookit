// Dump all references to the given rodata addresses and decompile the
// functions that reference them.  Used to recover RR3's material tag ->
// texture logic without symbols.
//
// usage: -postScript DumpTagRefs.java <outfile> <hexaddr> [<hexaddr> ...]
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

public class DumpTagRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DumpTagRefs <outfile> <hexaddr>...");
            return;
        }
        PrintWriter out = new PrintWriter(args[0], "UTF-8");
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Long> done = new HashSet<>();
        for (int i = 1; i < args.length; i++) {
            Address t = toAddr(args[i]);
            out.println("==== TARGET " + args[i] + " @ " + t);
            ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(t);
            int n = 0;
            while (it.hasNext()) {
                Reference r = it.next();
                Address from = r.getFromAddress();
                Function f = getFunctionContaining(from);
                out.println("  ref from " + from
                        + (f == null ? " (no function)" : " in " + f.getName() + " @ " + f.getEntryPoint()));
                n++;
                if (f != null && done.add(f.getEntryPoint().getOffset())) {
                    DecompileResults res = dec.decompileFunction(f, 120, monitor);
                    if (res != null && res.decompileCompleted()) {
                        out.println("----- DECOMP " + f.getName() + " @ " + f.getEntryPoint());
                        out.println(res.getDecompiledFunction().getC());
                    } else {
                        out.println("----- DECOMP FAILED for " + f.getName());
                    }
                }
            }
            out.println("  total refs: " + n);
        }
        out.close();
        dec.dispose();
        println("DumpTagRefs done -> " + args[0]);
    }
}
