// Sanity-check the loaded program against the raw file: read bytes at a few
// addresses and compare with what the caller expects.
//
// args: <outfile> <hexaddr> [<hexaddr> ...]
//
//@category RR3

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

import java.io.PrintWriter;

public class Bytes extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter pw = new PrintWriter(args[0], "UTF-8")) {
            pw.printf("PROGRAM %s  imageBase=%s  language=%s%n",
                    currentProgram.getName(),
                    currentProgram.getImageBase(),
                    currentProgram.getLanguageID());
            for (int i = 1; i < args.length; i++) {
                long v = Long.parseLong(args[i].replace("0x", ""), 16);
                Address a = toAddr(v);
                StringBuilder sb = new StringBuilder();
                for (int k = 0; k < 32; k++) {
                    try {
                        sb.append(String.format("%02x", getByte(a.add(k)) & 0xFF));
                    } catch (Exception e) {
                        sb.append("??");
                        break;
                    }
                }
                pw.printf("0x%08X  %s%n", v, sb);
            }
        }
        println("ok");
    }
}
