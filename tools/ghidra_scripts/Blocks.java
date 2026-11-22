// List the memory blocks Ghidra loaded, with their start/end and file offset.
//
// args: <outfile>
//
//@category RR3

import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;

import java.io.PrintWriter;

public class Blocks extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter pw = new PrintWriter(args[0], "UTF-8")) {
            pw.printf("PROGRAM %s  imageBase=%s%n",
                    currentProgram.getName(), currentProgram.getImageBase());
            for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
                pw.printf("%-24s start=0x%08X end=0x%08X size=0x%08X file=%d init=%s r=%s w=%s x=%s%n",
                        b.getName(), b.getStart().getOffset(), b.getEnd().getOffset(),
                        b.getSize(), b.getFileOffset(), b.isInitialized(),
                        b.isRead(), b.isWrite(), b.isExecute());
            }
        }
        println("ok");
    }
}
