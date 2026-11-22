// Decompile the function containing each given address, and list its callers
// and callees.  Used for code reached through the custom ARM64 xref scan.
//
// usage: -postScript DumpAt.java <outfile> <hexaddr> [<hexaddr> ...]
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

public class DumpAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: DumpAt <outfile> <hexaddr>...");
            return;
        }
        PrintWriter out = new PrintWriter(args[0], "UTF-8");
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        Set<Long> done = new HashSet<>();
        for (int i = 1; i < args.length; i++) {
            Address a = toAddr(args[i]);
            Function f = getFunctionContaining(a);
            out.println("==== ADDR " + args[i]);
            if (f == null) {
                out.println("  no function contains this address");
                continue;
            }
            out.println("  function " + f.getName() + " @ " + f.getEntryPoint()
                    + "  body " + f.getBody().getNumAddresses() + " bytes");
            ReferenceIterator it = currentProgram.getReferenceManager()
                    .getReferencesTo(f.getEntryPoint());
            while (it.hasNext()) {
                Reference r = it.next();
                Function c = getFunctionContaining(r.getFromAddress());
                out.println("    caller " + r.getFromAddress()
                        + (c == null ? "" : " in " + c.getName() + " @ " + c.getEntryPoint()));
            }
            Set<Function> callees = f.getCalledFunctions(monitor);
            for (Function c : callees) {
                out.println("    callee " + c.getName() + " @ " + c.getEntryPoint());
            }
            if (done.add(f.getEntryPoint().getOffset())) {
                DecompileResults res = dec.decompileFunction(f, 180, monitor);
                if (res != null && res.decompileCompleted()) {
                    out.println("----- DECOMP " + f.getName());
                    out.println(res.getDecompiledFunction().getC());
                } else {
                    out.println("----- DECOMP FAILED");
                }
            }
        }
        out.close();
        dec.dispose();
        println("DumpAt done -> " + args[0]);
    }
}
