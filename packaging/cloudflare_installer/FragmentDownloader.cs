// Cloudflare-only helper transport for immutable installer seed parts and the pinned overlay.
// Copyright (c) 2026 Ethan Prince. MIT license: ../../LICENSE.
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
    readonly string version;
    readonly Func<bool> stopping;
    readonly Action<long, string> report;
    readonly Action<int> pause;
    internal int Timeout = 30000;
    internal int ReadTimeout = 60000;
    internal int MaxFailures = 5;

    public FragmentDownloader(string origin, string version, Func<bool> stopping,
                              Action<long, string> report, Action<int> pause)
    {

        this.version = version;
        this.stopping = stopping;
        this.report = report;
        this.pause = pause;
    }

    public void FetchPart(FileStream file, Part part, int index, int count, long start)
    {
        int failures = 0;
        while (true)
        {
            long have = Math.Max(0, Math.Min(file.Length - start, part.Size));
            try
            {
                using (SHA256 sha = new SHA256CryptoServiceProvider())
                {
                    if (have > 0) Rehash(file, sha, start, have);
                    if (have < part.Size) ReceiveMirror(file, sha, part, start, ref have);
                    sha.TransformFinalBlock(new byte[0], 0, 0);
                    if (Hex(sha.Hash) == part.Sha256) return;
                }
                file.SetLength(start);
                throw new IOException("the downloaded part failed its SHA-256 check.");
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception error)
            {
                if (++failures > MaxFailures)
                    throw new Problem("The Cloudflare download could not be completed (" + error.Message.TrimEnd('.') + "). Check the connection and try again.");
                report(start + have, "The Cloudflare connection stopped. Retrying...");
                pause(1000 * failures);
            }
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
            {
                file.SetLength(start);
                throw new IOException("the server ignored the requested byte range; retry this part from its start.");
            }
        }
        if (have != part.Size) throw new IOException("the mirror did not complete the part.");
    }

    // offset and objectSize are relative to this HTTP object; have is relative to its original logical part.
    // Validate headers before writing, bound every read, and require EOF after the expected response bytes.
    bool Request(FileStream file, SHA256 sha, string url, long objectSize, long offset, long start, ref long have)
    {
        CheckStopped();
        Uri address = new Uri(url);
        if (address.Scheme != "https" || address.Host != "downloads.layeredhuman.com" || !address.IsDefaultPort
            || address.UserInfo.Length != 0 || address.Query.Length != 0 || address.Fragment.Length != 0
            || (address.AbsoluteUri != Release.OverlayUrl && !Regex.IsMatch(address.AbsolutePath,
                @"\A/releases/v4\.0\.11/install/windows/LayeredHuman-Setup-Windows\.exe\.part[0-9]{3}\.chunk[0-9]{3}\.bin\z")))
            throw new IOException("untrusted Cloudflare download URL.");
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(address);
        request.AllowAutoRedirect = false;
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
