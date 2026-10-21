// Derived helper transport for the unchanged v4.0.11 installer parts.
// Copyright (c) 2026 Ethan Prince. MIT license: ../upstream/LICENSE.
// C# 5 / .NET Framework; kept separate so transport tests need no window or installation.
using System;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

class Fragment
{
    public readonly string Url;
    public readonly long Offset, Size;
    public Fragment(string url, long offset, long size) { Url = url; Offset = offset; Size = size; }
}

class FragmentDownloader
{
    readonly string fallbackBase, version;
    readonly Func<bool> stopping;
    readonly Action<long, string> report;
    readonly Action<int> pause;
    internal int Timeout = 30000;
    internal int ReadTimeout = 60000;
    internal int MaxFailures = 5;

    public FragmentDownloader(string fallbackBase, string version, Func<bool> stopping,
                              Action<long, string> report, Action<int> pause)
    {
        this.fallbackBase = fallbackBase;
        this.version = version;
        this.stopping = stopping;
        this.report = report;
        this.pause = pause;
    }

    public void FetchPart(FileStream file, Part part, int index, int count, long start)
    {
        bool mirror = part.Fragments.Length > 0;
        int damaged = 0;
        while (true)
        {
            long have = Math.Max(0, Math.Min(file.Length - start, part.Size));
            using (SHA256 sha = new SHA256CryptoServiceProvider())
            {
                if (have > 0) Rehash(file, sha, start, have);
                if (mirror && have < part.Size)
                {
                    try { ReceiveMirror(file, sha, part, start, ref have); }
                    catch (OperationCanceledException) { throw; }
                    catch (Exception)
                    {
                        // The bytes written so far have original-part offsets. GitHub can resume here,
                        // even when a fragment failed halfway through. The original hash checks them all.
                        mirror = false;
                        report(start + have, "Trying the GitHub download...");
                    }
                }
                if (have < part.Size && !ReceiveFallback(file, sha, part, start, ref have))
                {
                    file.SetLength(start); // GitHub ignored Range: discard this part and request it whole.
                    mirror = false;
                    continue;
                }
                sha.TransformFinalBlock(new byte[0], 0, 0);
                if (Hex(sha.Hash) == part.Sha256) return;
            }
            // A corrupt mirror or stale local prefix must never contaminate the GitHub retry.
            file.SetLength(start);
            mirror = false;
            if (++damaged == 2)
                throw new Problem("Part " + (index + 1) + " of " + count + " arrived damaged twice. "
                                + "Click Try again to download it again. If this keeps happening, something on this "
                                + "computer or network (some antivirus or web filters do this) is changing the download.");
            report(start, "Checking the download failed. Trying GitHub again...");
        }
    }

    void Rehash(FileStream file, SHA256 sha, long start, long count)
    {
        byte[] buffer = new byte[1 << 20];
        file.Position = start;
        for (long done = 0; done < count; )
        {
            CheckStopped();
            int read = file.Read(buffer, 0, (int)Math.Min(buffer.Length, count - done));
            if (read == 0) throw new IOException("the downloaded file is shorter than it was.");
            sha.TransformBlock(buffer, 0, read, null, 0);
            done += read;
            report(start + done, "Checking what was already downloaded...");
        }
    }

    void ReceiveMirror(FileStream file, SHA256 sha, Part part, long start, ref long have)
    {
        foreach (Fragment fragment in part.Fragments)
        {
            if (have >= fragment.Offset + fragment.Size) continue;
            if (have < fragment.Offset) throw new IOException("the fragment layout is not contiguous.");
            long local = have - fragment.Offset;
            file.Position = start + have;
            if (!Request(file, sha, fragment.Url, fragment.Size, local, start, ref have))
                throw new IOException("the mirror ignored the requested byte range.");
        }
        if (have != part.Size) throw new IOException("the mirror did not complete the part.");
    }

    bool ReceiveFallback(FileStream file, SHA256 sha, Part part, long start, ref long have)
    {
        int failures = 0;
        while (have < part.Size)
        {
            CheckStopped();
            long before = have;
            try
            {
                file.Position = start + have;
                if (!Request(file, sha, fallbackBase + "/" + part.Name, part.Size, have, start, ref have)) return false;
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception error)
            {
                if (Gone(error))
                    throw new Problem("This version's installer is no longer on GitHub. Download the newest "
                                    + "installer from " + Release.Page + " and open that instead.");
                failures = have > before ? 1 : failures + 1;
                if (failures > MaxFailures)
                    throw new Problem("The installer could not be downloaded from GitHub (" + error.Message.TrimEnd('.')
                                    + "). Check that this computer is online, then click Try again.");
                for (int wait = 5 * failures; wait > 0; wait--)
                {
                    report(start + have, "The connection dropped. Trying again in " + wait + " s...");
                    pause(1000);
                }
            }
        }
        return true;
    }

    // offset and objectSize are relative to this HTTP object; have is relative to its original logical part.
    // Validate headers before writing, bound every read, and require EOF after the expected response bytes.
    bool Request(FileStream file, SHA256 sha, string url, long objectSize, long offset, long start, ref long have)
    {
        CheckStopped();
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
        request.UserAgent = "LayeredHuman-installer/" + version;
        request.Timeout = Timeout;
        request.ReadWriteTimeout = ReadTimeout;
        request.AutomaticDecompression = DecompressionMethods.None;
        if (offset > 0) request.AddRange(offset);
        HttpWebResponse response = null;
        bool complete = false;
        try
        {
            response = (HttpWebResponse)request.GetResponse();
            if (offset > 0 && response.StatusCode == HttpStatusCode.OK) return false;
            if (response.StatusCode == HttpStatusCode.PartialContent)
            {
                Match range = Regex.Match(response.Headers["Content-Range"] ?? "", @"\Abytes (\d+)-(\d+)/(\d+)\z");
                long first, last, whole;
                if (!range.Success || !long.TryParse(range.Groups[1].Value, out first)
                    || !long.TryParse(range.Groups[2].Value, out last) || !long.TryParse(range.Groups[3].Value, out whole)
                    || first != offset || last != objectSize - 1 || whole != objectSize)
                    throw new IOException("the server sent an unexpected Content-Range.");
            }
            else if (response.StatusCode != HttpStatusCode.OK || offset != 0)
                throw new IOException("the server did not send the requested byte range.");
            long remaining = objectSize - offset;
            if (response.ContentLength != remaining)
                throw new IOException("the server sent an unexpected Content-Length.");
            string encoding = response.Headers["Content-Encoding"];
            if (!string.IsNullOrEmpty(encoding) && encoding != "identity")
                throw new IOException("the server changed the download encoding.");
            using (Stream stream = response.GetResponseStream())
            {
                byte[] buffer = new byte[1 << 20];
                while (remaining > 0)
                {
                    CheckStopped();
                    int read = stream.Read(buffer, 0, (int)Math.Min(buffer.Length, remaining));
                    if (read == 0) throw new IOException("the connection closed early.");
                    CheckStopped();
                    file.Write(buffer, 0, read);
                    sha.TransformBlock(buffer, 0, read, null, 0);
                    have += read;
                    remaining -= read;
                    report(start + have, null);
                }
                if (stream.ReadByte() != -1) throw new IOException("the server sent extra bytes.");
            }
            complete = true;
            return true;
        }
        finally
        {
            if (!complete) request.Abort();
            if (response != null) response.Close();
        }
    }

    void CheckStopped() { if (stopping()) throw new OperationCanceledException(); }

    static bool Gone(Exception error)
    {
        WebException web = error as WebException;
        HttpWebResponse response = web == null ? null : web.Response as HttpWebResponse;
        return response != null
            && (response.StatusCode == HttpStatusCode.NotFound || response.StatusCode == HttpStatusCode.Gone);
    }

    static string Hex(byte[] bytes)
    {
        StringBuilder text = new StringBuilder(bytes.Length * 2);
        foreach (byte value in bytes) text.Append(value.ToString("x2"));
        return text.ToString();
    }
}
