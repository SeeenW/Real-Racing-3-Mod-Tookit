@echo off
rem Headless Ghidra launcher for RR3 reverse engineering.
rem   ghidra_headless.bat <projectdir> <projectname> -import <file> [options]
rem   ghidra_headless.bat -help
call "%~dp0rr3env.bat"
call "%GHIDRA_HOME%\support\analyzeHeadless.bat" %*
