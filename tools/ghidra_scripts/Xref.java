// List all references to one or more addresses using Ghidra's own reference
// database (far more reliable than a linear ADRP+ADD scan).
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//@category RR3

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

public class Xref extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("usage: Xref.java <outfile> <hexaddr> [<hexaddr> ...]");
            return;
        }
        String outPath = args[0];
        try (PrintWriter pw = new PrintWriter(outPath, "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", "").replace("0X", ""), 16);
                Address a = toAddr(v);
                pw.printf("TARGET 0x%08X%n", v);
                Data d = getDataAt(a);
                if (d != null && d.hasStringValue()) {
                    pw.printf("  string: %s%n", d.getValue().toString().replace("\n", "\\n"));
                }
                Reference[] refs = getReferencesTo(a);
                pw.printf("  refs=%d%n", refs.length);
                List<String> fnNames = new ArrayList<>();
                for (Reference r : refs) {
                    Address from = r.getFromAddress();
                    Function f = getFunctionContaining(from);
                    String fname = f == null ? "<no-fn>" : f.getName();
                    pw.printf("    from 0x%08X  type=%s  in %s (%s)%n",
                            from.getOffset(), r.getReferenceType(), fname,
                            f == null ? "-" : String.format("0x%08X", f.getEntryPoint().getOffset()));
                    if (f != null && !fnNames.contains(fname)) {
                        fnNames.add(fname);
                    }
                }
                pw.println();
            }
        }
        println("wrote " + outPath);
    }
}
