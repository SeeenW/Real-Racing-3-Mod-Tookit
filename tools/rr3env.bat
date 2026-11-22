@echo off
rem ---------------------------------------------------------------------------
rem  RR3 reversing toolchain environment
rem    JDK 21  : tools\jdk21            (portable copy of the JetBrains Runtime)
rem    Ghidra  : tools\ghidra_12.1.4_PUBLIC
rem  Source it from other scripts:  call "%~dp0rr3env.bat"
rem
rem  Ghidra's settings/cache/temp directories are redirected into tools\ via
rem  VMARGS lines in ghidra_12.1.4_PUBLIC\support\launch.properties (see there).
rem ---------------------------------------------------------------------------
set "TOOLS_DIR=%~dp0"
set "JAVA_HOME=%TOOLS_DIR%jdk21"
set "GHIDRA_HOME=%TOOLS_DIR%ghidra_12.1.4_PUBLIC"
set "PATH=%JAVA_HOME%\bin;%PATH%"
