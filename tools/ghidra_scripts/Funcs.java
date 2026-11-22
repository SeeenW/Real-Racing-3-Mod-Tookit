// Map addresses to the containing function (entry, size, name, caller count).
// Cheap: no decompilation.
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//@category RR3

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;

public class Funcs extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = args[0];
        Map<Long, StringBuilder> seen = new LinkedHashMap<>();
        try (PrintWriter pw = new PrintWriter(outPath, "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", "").replace("0X", ""), 16);
                Address a = toAddr(v);
                Function f = getFunctionContaining(a);
                if (f == null) {
                    pw.printf("%#010x  <no function>%n", v);
                    continue;
                }
                long e = f.getEntryPoint().getOffset();
                if (!seen.containsKey(e)) {
                    seen.put(e, new StringBuilder());
                    StringBuilder sb = seen.get(e);
                    int nrefs = getReferencesTo(f.getEntryPoint()).length;
                    sb.append(String.format("FN %#010x size=%d name=%s refs=%d body=0x%08X-0x%08X%n",
                            e, f.getBody().getNumAddresses(), f.getName(), nrefs,
                            e, f.getBody().getMaxAddress().getOffset()));
                }
                seen.get(e).append(String.format("   hit %#010x%n", v));
            }
            for (StringBuilder sb : seen.values()) {
                pw.print(sb);
            }
        }
        println("wrote " + outPath);
    }
}
