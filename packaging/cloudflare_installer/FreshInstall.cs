// Exact pinned overlay installation. No registry or user-profile writes occur
// in VerifyAndApply; the separate production entry invokes the existing Inno
// seed only for a new current-user installation.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;

class InventoryFile
{
    public string Name, Hash;
    public long Size;
}

static class FreshInstall
{
    static readonly string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\{BF742270-7363-48E6-81D2-B588178D84A6}_is1";

    public static string Destination
    {
        get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Layered Human"); }
    }

    public static void RequireFreshInstallation()
    {
        if (File.Exists(Path.Combine(Destination, "LayeredHuman.exe.installing")) ||
            File.Exists(Path.Combine(Destination, "AnatomyExplorer.exe.installing")))
            throw new Problem("An earlier fresh installation did not finish. Uninstall Layered Human in Windows Settings > Apps, then use File Explorer to delete the remaining incomplete application folder: " + Destination + ". Run this installer again after that. Your study data is kept separately.");
        foreach (RegistryHive hive in new[] { RegistryHive.CurrentUser, RegistryHive.LocalMachine })
            foreach (RegistryView view in new[] { RegistryView.Registry32, RegistryView.Registry64 })
                using (RegistryKey root = RegistryKey.OpenBaseKey(hive, view))
                using (RegistryKey key = root.OpenSubKey(UninstallKey))
                    if (key != null) throw new Problem("Layered Human is already installed. Open that copy and use its in-app updater.");
        if (Directory.Exists(Destination) || File.Exists(Destination))
            throw new Problem("The installation folder already exists: " + Destination + ". Open that copy and use its updater. This fresh installer will not replace it.");
        CheckParents(Path.GetDirectoryName(Destination));
    }

    public static string InstallSeed(string installer)
    {
        RequireFreshInstallation();
        // /CURRENTUSER overrides a prior machine-wide mode; the registry guard
        // above rejects all existing registrations before invoking the seed.
        // skipifsilent in the reviewed seed prevents its post-install app launch.
        ProcessStartInfo start = new ProcessStartInfo(installer,
            "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /TASKS=\"\" /DIR=\"" + Destination + "\"");
        start.UseShellExecute = false;
        using (Process child = Process.Start(start))
        {
            if (child == null) throw new Problem("Windows did not start the installer.");
            child.WaitForExit();
            if (Directory.Exists(Destination)) HoldExecutables(Destination);
            if (child.ExitCode != 0) throw new Problem("The installer did not finish (code " + child.ExitCode + "). Uninstall the incomplete copy in Windows Settings > Apps before trying again. Your study data is kept separately.");
        }
        return Destination;
    }

    public static string FetchOverlay(string folder, Func<bool> stopping, Action<long, string> report, Action<int> pause)
    {
        string path = Path.Combine(folder, "bridge-overlay.zip");
        Part part = new Part("bridge-overlay.zip", Release.OverlaySize, Release.OverlayHash,
                             new Fragment(Release.OverlayUrl, 0, Release.OverlaySize));
        using (FileStream output = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.Read))
        {
            if (output.Length > part.Size) output.SetLength(0);
            new FragmentDownloader(Release.Origin, Release.Version, stopping,
                delegate(long done, string note) { report(0, "Downloading the Cloudflare updater..."); }, pause).FetchPart(output, part, 0, 1, 0);
        }
        VerifyOverlay(path);
        return path;
    }

    public static string Resource(string name)
    {
        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
        using (StreamReader reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
    }

    static Dictionary<string, InventoryFile> Inventory(string name)
    {
        Dictionary<string, InventoryFile> result = new Dictionary<string, InventoryFile>(StringComparer.OrdinalIgnoreCase);
        foreach (string line in Resource(name).Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            string[] fields = line.TrimEnd('\r').Split('\t');
            long size;
            if (fields.Length != 4 || !long.TryParse(fields[1], out size) || size < 0 || !Regex.IsMatch(fields[2], @"\A[0-9a-f]{64}\z"))
                throw new Problem("The embedded inventory is invalid.");
            SafeRelative(fields[0]);
            result.Add(fields[0], new InventoryFile { Name = fields[0], Size = size, Hash = fields[2] });
        }
        return result;
    }

    public static string Hash(string path)
    {
        using (Stream file = File.OpenRead(path))
        using (SHA256 hash = SHA256.Create()) return Hex(hash.ComputeHash(file));
    }

    static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }

    static void SafeRelative(string name)
    {
        if (String.IsNullOrEmpty(name) || name.Contains("\\") || name.Contains(":") || name.StartsWith("/") || name.Contains("\n") || name.Contains("\r"))
            throw new Problem("An installation path is unsafe.");
        foreach (string part in name.Split('/'))
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" "))
                throw new Problem("An installation path is unsafe.");
    }

    static void CheckParents(string path)
    {
        for (string current = Path.GetFullPath(path); !String.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new Problem("The installation path contains a link. Choose a normal local folder.");
    }

    static string Child(string root, string name)
    {
        SafeRelative(name);
        string path = Path.GetFullPath(Path.Combine(root, name.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new Problem("The installation path escaped its folder.");
        CheckParents(path);
        return path;
    }

    static bool AllowedExtra(string name, bool installed)
    {
        if (name == "AnatomyExplorer-Windows-update.json" || name == "LayeredHuman-Windows-update.json") return true;
        // These are created outside the frozen tree by the verified original
        // Inno installer. They are never overlaid, launched or recursively removed.
        return installed && (name == "LICENSE.txt" || name == "THIRD_PARTY_LICENSES.md" ||
                             Regex.IsMatch(name, @"\Aunins[0-9]{3}\.(exe|dat|msg)\z"));
    }

    public static void Verify(string root, string resource, bool installed, bool held)
    {
        root = Path.GetFullPath(root);
        CheckParents(root);
        Dictionary<string, InventoryFile> expected = Inventory(resource);
        HashSet<string> directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (InventoryFile entry in expected.Values)
        {
            string name = entry.Name;
            for (int index = name.LastIndexOf('/'); index >= 0; index = name.LastIndexOf('/', index - 1))
            {
                directories.Add(name.Substring(0, index));
                if (index == 0) break;
            }
            string actual = held && (name == "LayeredHuman.exe" || name == "AnatomyExplorer.exe") ? name + ".installing" : name;
            string path = Child(root, actual);
            if (!File.Exists(path) || new FileInfo(path).Length != entry.Size || Hash(path) != entry.Hash)
                throw new Problem("Installation verification failed: " + name + ". The application was not opened.");
        }
        Stack<string> todo = new Stack<string>();
        todo.Push(root);
        int count = 0;
        while (todo.Count > 0)
            foreach (string path in Directory.GetFileSystemEntries(todo.Pop()))
            {
                if (++count > 200000) throw new Problem("The installation has too many files.");
                FileAttributes attrs = File.GetAttributes(path);
                if ((attrs & FileAttributes.ReparsePoint) != 0) throw new Problem("Unexpected link in the installation.");
                string name = path.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace('\\', '/');
                if ((attrs & FileAttributes.Directory) != 0)
                {
                    if (!directories.Contains(name)) throw new Problem("Unexpected directory in the installation: " + name);
                    todo.Push(path);
                }
                else
                {
                    if (held && (name == "LayeredHuman.exe.installing" || name == "AnatomyExplorer.exe.installing"))
                        name = name.Substring(0, name.Length - ".installing".Length);
                    if (!expected.ContainsKey(name) && !AllowedExtra(name, installed))
                        throw new Problem("Unexpected file in the installation: " + name);
                }
            }
    }

    public static void VerifyOverlay(string path)
    {
        if (!File.Exists(path) || new FileInfo(path).Length != Release.OverlaySize || Hash(path) != Release.OverlayHash)
            throw new Problem("The Cloudflare update did not pass its checksum. Run the installer again.");
    }

    public static void VerifyAndApply(string root, string overlay, bool installed)
    {
        root = Path.GetFullPath(root);
        CheckParents(root);
        VerifyOverlay(overlay);
        // A partially installed copy must never launch the legacy GitHub client.
        // Held executables are restored only after the final full inventory passes.
        HoldExecutables(root);
        try
        {
            // Refuse any unexpected seed bytes. A retry after a fully applied
            // overlay is valid; incomplete overlays are safely refused.
            try { Verify(root, "base-inventory.tsv", installed, true); }
            catch (Problem) { Verify(root, "inventory.tsv", installed, true); }
            Dictionary<string, InventoryFile> final = Inventory("inventory.tsv");
            HashSet<string> expected = new HashSet<string>(StringComparer.Ordinal);
            foreach (string name in Resource("delta.txt").Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries))
                expected.Add("payload/" + name.TrimEnd('\r'));
            expected.Add("metadata/LayeredHuman-Windows-update.json");
            expected.Add("metadata/AnatomyExplorer-Windows-update.json");
            ApplyArchive(root, overlay, final, expected);
            Verify(root, "inventory.tsv", installed, true);
            foreach (string name in new[] { "LayeredHuman.exe", "AnatomyExplorer.exe" })
                File.Move(Child(root, name + ".installing"), Child(root, name));
        }
        catch { throw; } // Retain held launchers and failure evidence; never launch a partial copy.
    }

    static void HoldExecutables(string root)
    {
        foreach (string name in new[] { "LayeredHuman.exe", "AnatomyExplorer.exe" })
        {
            string path = Child(root, name), hold = Child(root, name + ".installing");
            if (File.Exists(path) && File.Exists(hold)) throw new Problem("Ambiguous interrupted installation.");
            if (File.Exists(path)) File.Move(path, hold);
        }
    }

    static void ApplyArchive(string root, string overlay, Dictionary<string, InventoryFile> final, HashSet<string> expected)
    {
            using (ZipArchive zip = ZipFile.OpenRead(overlay))
            {
                if (zip.Entries.Count != expected.Count) throw new Problem("The overlay has an unexpected inventory.");
                HashSet<string> seen = new HashSet<string>(StringComparer.Ordinal);
                foreach (ZipArchiveEntry entry in zip.Entries)
                {
                    if (!expected.Contains(entry.FullName) || !seen.Add(entry.FullName)) throw new Problem("Unexpected overlay path.");
                    string name = entry.FullName.Substring(entry.FullName.IndexOf('/') + 1);
                    InventoryFile identity;
                    if (!final.TryGetValue(name, out identity) || entry.Length != identity.Size) throw new Problem("Unexpected overlay size.");
                    string target = Child(root, name), temporary = target + ".cf-overlay";
                    if (File.Exists(temporary) || Directory.Exists(temporary)) throw new Problem("An overlay temporary file already exists.");
                    try
                    {
                        using (Stream input = entry.Open())
                        using (FileStream output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write))
                        {
                            byte[] buffer = new byte[1 << 20];
                            long count = 0;
                            int read;
                            while ((read = input.Read(buffer, 0, buffer.Length)) > 0)
                            {
                                count += read;
                                if (count > identity.Size) throw new Problem("The overlay exceeded its file limit.");
                                output.Write(buffer, 0, read);
                            }
                            if (count != identity.Size) throw new Problem("The overlay ended early.");
                            output.Flush(true);
                        }
                        if (Hash(temporary) != identity.Hash) throw new Problem("An overlay file failed its checksum.");
                        if (File.Exists(target)) File.Replace(temporary, target, null);
                        else File.Move(temporary, target);
                    }
                    finally { if (File.Exists(temporary)) File.Delete(temporary); }
                }
            }
    }
}
