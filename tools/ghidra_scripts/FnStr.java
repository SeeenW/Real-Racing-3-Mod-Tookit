// Dump a function's instructions in order, annotating each instruction that
// references a string with the string value.  This makes the load order of an
// asset loader readable even when the decompiler drops the literals.
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//@category RR3

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;

public class FnStr extends GhidraScript {

    private boolean isPrologue(int w) {
        return (w & 0xFFE07FFF) == 0xA9807BFD;
    }

    private long findEntry(long addr) throws Exception {
        long a = addr & ~3L;
        for (int k = 0; k < 4000; k++) {
            if (a < 0x100000L) break;
            if (isPrologue(getInt(toAddr(a)))) return a;
            a -= 4;
        }
        return addr;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter pw = new PrintWriter(args[0], "UTF-8")) {
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", ""), 16);
                long entry = findEntry(v);
                Function f = getFunctionAt(toAddr(entry));
                if (f == null) f = getFunctionContaining(toAddr(entry));
                pw.printf("### probe 0x%08X -> entry 0x%08X%n", v, entry);
                if (f == null) { pw.println("NO FUNCTION"); continue; }
                pw.printf("FUNCTION %s @0x%08X size=%d%n", f.getName(),
                        f.getEntryPoint().getOffset(), f.getBody().getNumAddresses());
                InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
                while (it.hasNext()) {
                    Instruction ins = it.next();
                    StringBuilder note = new StringBuilder();
                    for (Reference r : ins.getReferencesFrom()) {
                        Address t = r.getToAddress();
                        if (t == null) continue;
                        Data d = getDataAt(t);
                        if (d != null && d.hasStringValue()) {
                            note.append("   ; \"")
                                .append(d.getValue().toString().replace("\n", "\\n"))
                                .append("\" @0x").append(String.format("%08X", t.getOffset()));
                        }
                    }
                    pw.printf("0x%08X  %-44s%s%n", ins.getAddress().getOffset(),
                            ins.toString(), note);
                }
                pw.println();
            }
        }
        println("ok");
    }
}
