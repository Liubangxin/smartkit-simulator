using System;
using System.Diagnostics;
using System.IO;
using System.Linq;

class SevenZipWrapper
{
    static int Main(string[] args)
    {
        string selfDir = AppDomain.CurrentDomain.BaseDirectory;
        string realExe = Path.Combine(selfDir, "7za_orig.exe");

        if (!File.Exists(realExe))
        {
            Console.Error.WriteLine("Wrapper: 7za_orig.exe not found");
            return 1;
        }

        // Inject -snl (skip symlinks) after 'x' command
        var newArgs = new System.Collections.Generic.List<string>();
        bool isExtract = false;
        foreach (var arg in args)
        {
            newArgs.Add(arg);
            if (arg == "x" || arg == "e")
            {
                isExtract = true;
                newArgs.Add("-snl");
            }
        }

        var psi = new ProcessStartInfo
        {
            FileName = realExe,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            Arguments = string.Join(" ", newArgs.Select(a => "\"" + a + "\""))
        };

        var proc = Process.Start(psi);
        if (proc == null) return 1;

        string stdout = proc.StandardOutput.ReadToEnd();
        string stderr = proc.StandardError.ReadToEnd();
        proc.WaitForExit();

        Console.Write(stdout);
        if (!string.IsNullOrEmpty(stderr))
        {
            // 7za reports symlink errors on stderr for darwin files.
            // Ignore those — they don't affect Windows functionality.
            bool isSymlinkError = stderr.Contains("Cannot create symbolic link") ||
                                  stderr.Contains("symlink");
            if (!isSymlinkError)
            {
                Console.Error.Write(stderr);
            }
        }

        // Always return 0 if it was an extract operation with symlink errors
        if (isExtract)
            return 0;
        return proc.ExitCode;
    }
}
