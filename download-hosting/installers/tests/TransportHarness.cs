using System;
using System.Collections.Generic;
using System.IO;

static class TransportHarness
{
    // Console-only test entry point: never constructs a Form or opens an installer.
    static int Main(string[] args)
    {
        try
        {
            string server = args[0];
            string path = args[1];
            long start = long.Parse(args[2]);
            long size = long.Parse(args[3]);
            List<Fragment> fragments = new List<Fragment>();
            long offset = 0;
            foreach (string value in args[5].Split(','))
            {
                long length = long.Parse(value);
                fragments.Add(new Fragment(server + "/r2/" + fragments.Count, offset, length));
                offset += length;
            }
            Part part = new Part("part.bin", size, args[4], fragments.ToArray());
            FragmentDownloader downloader = new FragmentDownloader(server + "/gh", "test", () => false,
                delegate(long done, string note) { }, delegate(int milliseconds) { });
            downloader.Timeout = 200;
            downloader.ReadTimeout = 200;
            downloader.MaxFailures = 1;
            using (FileStream file = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite))
                downloader.FetchPart(file, part, 0, 1, start);
            Console.WriteLine("verified");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
