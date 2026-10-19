// Install-Anatomy-Explorer-Windows.exe, the program new Windows users download. The Windows installer is bigger than
// GitHub allows in one file, so a release carries it in parts. This program downloads them with one progress bar,
// checks each part's SHA-256 as it arrives and writes them straight into one installer file. It then opens the
// installer, and deletes the download once Anatomy Explorer is installed. Run again after a stop, it carries on where
// the download left off.
//
// Release.cs, written by packaging/prepare_release_assets.py for each release, says where the parts are and what they
// hash to. C# 5 and ASCII only: the .NET Framework compiler that comes with Windows builds it, so no SDK is needed.
//
// Options for tests: --work DIR (download folder), --status FILE (no dialogs; the outcome is written to FILE),
// --download-only (download and check, but do not open the installer).
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

class Part
{
    public readonly string Name;
    public readonly long Size;
    public readonly string Sha256;

    public Part(string name, long size, string sha256)
    {
        Name = name;
        Size = size;
        Sha256 = sha256;
    }
}

// Something the person can act on; the message is shown as it is.
class Problem : Exception
{
    public Problem(string message) : base(message) { }
}

static class Program
{
    public static readonly string Title = "Install " + Release.AppName;

    [STAThread]
    static int Main(string[] args)
    {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                   "AnatomyExplorer-download");
        string status = null;
        bool downloadOnly = false;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--work" && i + 1 < args.Length) root = args[++i];
            else if (args[i] == "--status" && i + 1 < args.Length) status = args[++i];
            else if (args[i] == "--download-only") downloadOnly = true;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        bool first;
        using (Mutex running = new Mutex(true, "Local\\AnatomyExplorer-install-download", out first))
        {
            if (!first)
            {
                if (status == null)
                    MessageBox.Show(Release.AppName + " is already downloading in another window.", Title,
                                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 3;
            }
            // GitHub accepts only TLS 1.2 or newer, which a .NET 4 program does not offer unless asked to.
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            InstallerForm form = new InstallerForm(root, status, downloadOnly);
            Application.Run(form);
            return form.Result;
        }
    }
}

class InstallerForm : Form
{
    enum Stage { Download, Failed, Installing, NotInstalled }

    // 0 installed (or downloaded, with --download-only), 1 failed, 2 the installer closed early, 4 stopped.
    public int Result = 1;

    readonly string root, folder, target, statusFile;
    readonly bool downloadOnly;
    readonly long total;
    readonly float scale;
    readonly Label heading = new Label(), info = new Label(), progress = new Label();
    readonly ProgressBar bar = new ProgressBar();
    readonly Button action = new Button(), close = new Button();
    readonly Queue<long[]> samples = new Queue<long[]>();  // {milliseconds, bytes} of the last few seconds, for the speed
    Stage stage = Stage.Download;
    Thread worker;
    Stopwatch clock;
    long lastReport = -1000;
    string lastNote;
    volatile bool stopping;
    bool closing;

    public InstallerForm(string root, string statusFile, bool downloadOnly)
    {
        this.root = root;
        this.statusFile = statusFile;
        this.downloadOnly = downloadOnly;
        folder = Path.Combine(root, Release.Version);
        target = Path.Combine(folder, Release.Setup);
        foreach (Part part in Release.Parts) total += part.Size;

        // The layout is in pixels at 100% display scale, scaled here to the display. (Windows Forms' own scaling
        // scaled two of the labels twice at 150%.) Fonts are in points, so they follow the display by themselves.
        using (Graphics screen = Graphics.FromHwnd(IntPtr.Zero)) scale = screen.DpiX / 96F;
        AutoScaleMode = AutoScaleMode.None;
        Text = Program.Title;
        Font = SystemFonts.MessageBoxFont;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(Px(500), Px(214));
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
        catch (Exception) { }

        Place(heading, 20, 16, 460, 28);
        heading.Font = new Font(Font.FontFamily, 12F);
        Place(info, 20, 48, 460, 64);
        Place(bar, 20, 116, 460, 20);
        bar.Maximum = 1000;
        Place(progress, 20, 142, 460, 20);
        Place(action, 214, 174, 160, 28);
        Place(close, 384, 174, 96, 28);
        action.Click += delegate { OnAction(); };
        close.Click += delegate { Close(); };
        Controls.AddRange(new Control[] { heading, info, bar, progress, action, close });
        Shown += delegate { StartDownload(); };
    }

    int Px(int pixels)
    {
        return (int)Math.Round(pixels * scale);
    }

    void Place(Control control, int x, int y, int width, int height)
    {
        control.SetBounds(Px(x), Px(y), Px(width), Px(height));
    }

    void StartDownload()
    {
        stage = Stage.Download;
        heading.Text = "Downloading " + Release.AppName + " " + Release.Version;
        info.Text = "The installer is " + Amount(total) + ". It opens by itself when the download is done. If the "
                  + "download stops, open this program again and it carries on where it left off.";
        progress.Text = "Starting...";
        bar.Visible = true;
        action.Visible = false;
        close.Text = "Cancel";
        close.Enabled = true;
        stopping = false;
        samples.Clear();
        lastNote = null;
        clock = Stopwatch.StartNew();
        lastReport = -1000;
        worker = new Thread(Download);
        worker.IsBackground = true;
        worker.Start();
    }

    // Runs on the worker thread.
    void Download()
    {
        try
        {
            Directory.CreateDirectory(folder);
            RemoveOtherDownloads();
            using (FileStream file = new FileStream(target, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.Read))
            {
                if (file.Length > total) file.SetLength(total);
                CheckSpace(total - file.Length);
                long start = 0;
                for (int i = 0; i < Release.Parts.Length; i++)
                {
                    FetchPart(file, i, start);
                    start += Release.Parts[i].Size;
                }
            }
            Ui(Downloaded);
        }
        catch (OperationCanceledException)
        {
            Ui(delegate { Finish(4, "stopped"); });
        }
        catch (Problem problem)
        {
            Ui(delegate { Fail("The download stopped", problem.Message); });
        }
        catch (Exception error)
        {
            Ui(delegate { Fail("The download stopped", "Something went wrong: " + error.Message
                                                     + " Click Try again to carry on."); });
        }
    }

    // Brings part `index`, which starts at byte `start` of the installer, into the file and checks it. Bytes already
    // there from an earlier run are checked along with the rest and kept when the part comes out right.
    void FetchPart(FileStream file, int index, long start)
    {
        Part part = Release.Parts[index];
        int damaged = 0;
        while (true)
        {
            long have = Math.Max(0, Math.Min(file.Length - start, part.Size));
            SHA256 sha = new SHA256CryptoServiceProvider();
            try
            {
                if (have > 0) Rehash(file, sha, start, have);
                if (!Receive(file, sha, part, start, ref have))
                {
                    file.SetLength(start);  // the server would not send just the rest: fetch the part whole
                    continue;
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                if (Hex(sha.Hash) == part.Sha256) return;
            }
            finally
            {
                sha.Dispose();
            }
            file.SetLength(start);
            if (++damaged == 2)
                throw new Problem("Part " + (index + 1) + " of " + Release.Parts.Length + " arrived damaged twice. "
                                + "Click Try again to download it again. If this keeps happening, something on this "
                                + "computer or network (some antivirus or web filters do this) is changing the download.");
        }
    }

    void Rehash(FileStream file, SHA256 sha, long start, long count)
    {
        byte[] buffer = new byte[1 << 20];
        file.Position = start;
        for (long done = 0; done < count; )
        {
            if (stopping) throw new OperationCanceledException();
            int read = file.Read(buffer, 0, (int)Math.Min(buffer.Length, count - done));
            if (read == 0) throw new IOException("the downloaded file is shorter than it was.");
            sha.TransformBlock(buffer, 0, read, null, 0);
            done += read;
            Report(start + done, "Checking what was already downloaded...");
        }
    }

    // Downloads the rest of the part, from byte `have` on, trying again when the connection drops. False when the
    // server sent the part from its beginning instead of the rest.
    bool Receive(FileStream file, SHA256 sha, Part part, long start, ref long have)
    {
        int failures = 0;
        while (have < part.Size)
        {
            long before = have;
            try
            {
                file.Position = start + have;
                if (!Request(file, sha, part, start, ref have)) return false;
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception error)
            {
                if (Gone(error))
                    throw new Problem("This version's installer is no longer on GitHub. Download the newest "
                                    + "installer from " + Release.Page + " and open that instead.");
                failures = have > before ? 1 : failures + 1;
                if (failures > 5)
                    throw new Problem("The installer could not be downloaded from GitHub (" + error.Message.TrimEnd('.')
                                    + "). Check that this computer is online, then click Try again.");
                for (int wait = 5 * failures; wait > 0; wait--)
                {
                    Report(start + have, "The connection dropped. Trying again in " + wait + " s...");
                    Pause(1000);
                }
            }
        }
        return true;
    }

    bool Request(FileStream file, SHA256 sha, Part part, long start, ref long have)
    {
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(Release.Base + "/" + part.Name);
        request.UserAgent = "AnatomyExplorer-installer/" + Release.Version;
        request.Timeout = 30000;
        request.ReadWriteTimeout = 60000;
        if (have > 0) request.AddRange(have);
        HttpWebResponse response = null;
        try
        {
            response = (HttpWebResponse)request.GetResponse();
            if (have > 0 && response.StatusCode != HttpStatusCode.PartialContent) return false;
            Stream stream = response.GetResponseStream();
            byte[] buffer = new byte[1 << 20];
            while (have < part.Size)
            {
                int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, part.Size - have));
                if (read == 0) throw new IOException("the connection closed early.");
                if (stopping) throw new OperationCanceledException();
                file.Write(buffer, 0, read);
                sha.TransformBlock(buffer, 0, read, null, 0);
                have += read;
                Report(start + have, null);
            }
            return true;
        }
        finally
        {
            if (have < part.Size) request.Abort();  // drop the connection rather than read the rest of it
            if (response != null) response.Close();
        }
    }

    static bool Gone(Exception error)
    {
        WebException web = error as WebException;
        HttpWebResponse response = web == null ? null : web.Response as HttpWebResponse;
        return response != null
            && (response.StatusCode == HttpStatusCode.NotFound || response.StatusCode == HttpStatusCode.Gone);
    }

    void Pause(int milliseconds)
    {
        for (int waited = 0; waited < milliseconds; waited += 100)
        {
            if (stopping) throw new OperationCanceledException();
            Thread.Sleep(100);
        }
    }

    void CheckSpace(long needed)
    {
        needed += 200000000L;  // room to spare
        DriveInfo drive;
        try { drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(folder))); }
        catch (ArgumentException) { return; }  // a network folder: the download will find out
        if (drive.AvailableFreeSpace < needed)
            throw new Problem("There is not enough free space on drive " + drive.Name.TrimEnd('\\') + ". The download "
                            + "needs " + Amount(needed) + " and " + Amount(drive.AvailableFreeSpace) + " is free. Free "
                            + "up some space, then click Try again.");
    }

    // An older version's half-finished download is no use to this one.
    void RemoveOtherDownloads()
    {
        string mine = Path.GetFullPath(folder).TrimEnd('\\');
        foreach (string other in Directory.GetDirectories(root))
            if (!string.Equals(Path.GetFullPath(other).TrimEnd('\\'), mine, StringComparison.OrdinalIgnoreCase))
                try { Directory.Delete(other, true); }
                catch (Exception) { }
    }

    // Shows how far the download is, at most five times a second (and whenever the note changes). A null note means
    // downloading: the line then shows the amount, the speed and the time left.
    void Report(long done, string note)
    {
        long now = clock.ElapsedMilliseconds;
        if (now - lastReport < 200 && note == lastNote) return;
        lastReport = now;
        lastNote = note;
        string text;
        if (note != null)
        {
            samples.Clear();
            text = note;
        }
        else
        {
            samples.Enqueue(new long[] { now, done });
            while (now - samples.Peek()[0] > 5000) samples.Dequeue();
            long[] oldest = samples.Peek();
            double speed = now - oldest[0] >= 1000 ? (done - oldest[1]) * 1000.0 / (now - oldest[0]) : 0;
            text = Amount(done) + " of " + Amount(total);
            if (speed > 0)
                text += "   ·   " + (speed / 1e6).ToString("0.0") + " MB/s   ·   " + TimeLeft((total - done) / speed);
        }
        int value = (int)Math.Min(1000, done * 1000 / total);
        Ui(delegate
        {
            bar.Value = value;
            progress.Text = text;
            Text = value / 10 + "% - " + Program.Title;
        });
    }

    void Downloaded()
    {
        bar.Value = 1000;
        Text = Program.Title;
        if (stopping) Finish(4, "stopped");
        else if (downloadOnly) Finish(0, "downloaded");
        else OpenInstaller();
    }

    void OpenInstaller()
    {
        stage = Stage.Installing;
        heading.Text = "Installing " + Release.AppName;
        info.Text = "Follow the steps in the " + Release.AppName + " Setup window. This window closes by itself once "
                  + Release.AppName + " is installed.";
        progress.Text = "";
        bar.Visible = false;
        action.Visible = false;
        close.Text = "Close";
        close.Enabled = true;
        Process setup;
        try
        {
            ProcessStartInfo start = new ProcessStartInfo(target);
            start.UseShellExecute = true;
            start.WorkingDirectory = folder;
            setup = Process.Start(start);
        }
        catch (Exception error)
        {
            Fail("The installer did not open", "Windows could not open the installer (" + error.Message.TrimEnd('.')
                                              + "). Click Try again.");
            return;
        }
        if (setup == null)
        {
            Finish(0, "opened");
            return;
        }
        Thread waiter = new Thread(() =>
        {
            setup.WaitForExit();
            int code = -1;
            try { code = setup.ExitCode; }
            catch (Exception) { }
            Ui(delegate { InstallerClosed(code); });
        });
        waiter.IsBackground = true;
        waiter.Start();
    }

    void InstallerClosed(int code)
    {
        if (code == 0)
        {
            DeleteDownload();
            Finish(0, "installed");
            return;
        }
        stage = Stage.NotInstalled;
        Result = 2;
        heading.Text = Release.AppName + " was not installed";
        info.Text = "The installer closed before it finished. Click Open the installer to try again. Close deletes the "
                  + "downloaded installer.";
        action.Text = "Open the installer";
        action.Visible = true;
        if (statusFile != null) Finish(2, "not installed|" + code);
        else Activate();
    }

    void Fail(string title, string message)
    {
        if (stopping)
        {
            Finish(4, "stopped");
            return;
        }
        stage = Stage.Failed;
        Result = 1;
        Text = Program.Title;
        heading.Text = title;
        info.Text = message;
        progress.Text = "";
        action.Text = "Try again";
        action.Visible = true;
        close.Text = "Close";
        close.Enabled = true;
        if (statusFile != null) Finish(1, "failed|" + message);
    }

    void OnAction()
    {
        if (stage == Stage.Failed) StartDownload();
        else if (stage == Stage.NotInstalled) OpenInstaller();
    }

    void Finish(int code, string outcome)
    {
        Result = code;
        if (statusFile != null)
            try { File.WriteAllText(statusFile, outcome); }
            catch (Exception) { }
        closing = true;
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        base.OnFormClosing(e);
        if (closing) return;
        if (stage == Stage.Download)
        {
            e.Cancel = true;
            if (stopping) return;
            if (statusFile == null
                && MessageBox.Show(this, "Stop downloading? What has downloaded so far is kept, so opening this program "
                                         + "again carries on from there.", Program.Title, MessageBoxButtons.YesNo,
                                   MessageBoxIcon.Question) != DialogResult.Yes)
                return;
            stopping = true;
            if (worker != null && worker.IsAlive)
            {
                close.Enabled = false;
                progress.Text = "Stopping...";
            }
            else
            {
                closing = true;
                BeginInvoke((MethodInvoker)Close);
            }
            return;
        }
        if (stage == Stage.NotInstalled) DeleteDownload();
    }

    void DeleteDownload()
    {
        try { Directory.Delete(folder, true); }
        catch (Exception) { }
        try { Directory.Delete(root); }  // only when nothing else is left in it
        catch (Exception) { }
    }

    void Ui(MethodInvoker step)
    {
        try { BeginInvoke(step); }
        catch (InvalidOperationException) { }  // the window is already gone
    }

    static string Amount(long bytes)
    {
        return bytes >= 1000000000L ? (bytes / 1e9).ToString("0.00") + " GB" : (bytes / 1e6).ToString("0") + " MB";
    }

    static string TimeLeft(double seconds)
    {
        if (seconds < 60) return "less than a minute left";
        long minutes = (long)Math.Ceiling(seconds / 60);
        if (minutes < 60) return "about " + minutes + " minutes left";
        return "about " + minutes / 60 + " h " + minutes % 60 + " min left";
    }

    static string Hex(byte[] bytes)
    {
        StringBuilder text = new StringBuilder(bytes.Length * 2);
        foreach (byte b in bytes) text.Append(b.ToString("x2"));
        return text.ToString();
    }
}
