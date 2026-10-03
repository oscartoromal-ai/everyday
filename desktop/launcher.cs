// The installed app's launcher: the "Personal Calendar.exe" at the top of its
// folder, which its Start menu entry, taskbar pin and sign-in entry start. It
// starts the current version, from the folder of its own that current.txt
// names (app-<commit>), with the arguments it was given. An update stages the
// next version beside the running one, and that one rewrites current.txt as
// it takes over (app/desktop/update.py), so the launcher never changes.
//
// Built by desktop/build.ps1 with the C# compiler of the .NET Framework that
// comes with Windows.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Personal Calendar")]
[assembly: AssemblyProduct("Personal Calendar")]

static class Launcher
{
    const string Name = "Personal Calendar";

    [DllImport("user32.dll")]
    static extern bool AllowSetForegroundWindow(int processId);

    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string exe;
        try
        {
            string version = File.ReadAllText(Path.Combine(root, "current.txt")).Trim();
            exe = Path.Combine(Path.Combine(root, version), Name + ".exe");
            if (!File.Exists(exe)) throw new FileNotFoundException("Not found: " + exe);
        }
        catch (Exception e)
        {
            MessageBox.Show(Name + " is not installed whole; install it again.\n\n" + e.Message,
                Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var start = new ProcessStartInfo(exe, Join(args)) { UseShellExecute = false };
        using (Process app = Process.Start(start))
        {
            // Launched by the user, this has the foreground to hand on.
            AllowSetForegroundWindow(app.Id);
        }
        return 0;
    }

    // The arguments as one command line, each quoted as the C runtime reads it.
    static string Join(string[] args)
    {
        var line = new StringBuilder();
        foreach (string arg in args)
        {
            if (line.Length > 0) line.Append(' ');
            line.Append('"');
            int slashes = 0;
            foreach (char c in arg)
            {
                if (c == '\\') { slashes++; continue; }
                line.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
                slashes = 0;
                line.Append(c);
            }
            line.Append('\\', slashes * 2);
            line.Append('"');
        }
        return line.ToString();
    }
}
