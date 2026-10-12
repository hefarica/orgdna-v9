using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Management;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
[assembly: AssemblyTitle("DSH Reiniciar")]
[assembly: AssemblyDescription("Reinicio controlado del perfil DSH actual. No reinstala el Harness ni restaura historiales antiguos.")]
[assembly: AssemblyCompany("HFRC")]
[assembly: AssemblyProduct("DSH Reiniciar")]
[assembly: AssemblyVersion("1.1.1.0")]
[assembly: AssemblyFileVersion("1.1.1.0")]

internal static class Program {
    internal const string Title = "DSH | Reiniciar mi entorno";
    internal const string CoreSha = "1384b5b46376f5f2ef53f7320fc1604dce4d099ac33a5166f9476765f6d0065a";
    static JavaScriptSerializer Serializer() { return new JavaScriptSerializer { MaxJsonLength = 8 * 1024 * 1024 }; }
    internal static string Hash(byte[] b) { using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(b)).Replace("-", "").ToLowerInvariant(); }
    internal static string Text(IDictionary<string,object> d, string k) { return d.ContainsKey(k) && d[k] != null ? Convert.ToString(d[k]) : ""; }
    [STAThread]
    static int Main(string[] args) {
        try {
            if(args.Length==2 && args[0]=="--probe") {
                try {
                    var q=Serializer().Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(args[1])));
                    Console.WriteLine(Serializer().Serialize(Native.Request(q)));return 0;
                }catch(Exception e){Console.WriteLine(Serializer().Serialize(new {error="Windows no completo la operacion de identidad/cierre: "+e.Message,code=e is UnauthorizedAccessException || e is System.ComponentModel.Win32Exception ? "IDENTITY_PERMISSION":"WINDOWS_OPERATION"}));return 1;}
            }
            string[] allowed={"--headless","--no-open","--check-only","--self-test","--reuse","--restart","--allow-legacy-stop","--elevated"};
            if(args.Any(a=>!allowed.Contains(a)))throw new Exception("Argumento no reconocido.");
            if(args.Contains("--self-test"))return SelfTest();
            bool headless=args.Contains("--headless");int result=1;
            var sid=WindowsIdentity.GetCurrent().User;
            var security=new MutexSecurity();security.AddAccessRule(new MutexAccessRule(sid,MutexRights.FullControl,AccessControlType.Allow));
            bool created;using(var mutex=new Mutex(false,"Local\\HFRC_DSH_RESTART_V11_"+sid.Value,out created,security)) {
                bool held;try{held=mutex.WaitOne(0);}catch(AbandonedMutexException){held=true;}
                if(!held){Native.Activate(Title);Console.WriteLine("{\"status\":\"ALREADY_RESTARTING\",\"noDuplicate\":true}");return 0;}
                try {
                    string root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"DSH_LAUNCHER");EnsurePrivateRoot(root,sid);
                    if(headless)result=Execute(root,args,delegate(string m){Console.WriteLine(m);});
                    else {Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);using(var form=new LaunchForm(root,args)){Application.Run(form);result=form.ExitCode;}}
                }finally{mutex.ReleaseMutex();}
            }
            if(result==42) {
                var again=args.Where(x=>x!="--elevated").Concat(new[]{"--elevated"});
                var pi=new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,String.Join(" ",again.Select(Quote).ToArray())){UseShellExecute=true,Verb="runas"};
                using(var child=Process.Start(pi)){child.WaitForExit();return child.ExitCode;}
            }
            return result;
        }catch(Exception e){Console.WriteLine(Serializer().Serialize(new {status="LAUNCHER_ERROR",message=e.Message}));if(!args.Contains("--headless"))MessageBox.Show(e.Message,Title,MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
    static void EnsurePrivateRoot(string root, SecurityIdentifier sid) {
        if (Directory.Exists(root)) { if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0) throw new Exception("La carpeta del lanzador no puede ser un enlace."); return; }
        Directory.CreateDirectory(root);
        var sec = new DirectorySecurity(); sec.SetAccessRuleProtection(true, false);
        foreach (var id in new[] { sid, new SecurityIdentifier("S-1-5-18"), new SecurityIdentifier("S-1-5-32-544") })
            sec.AddAccessRule(new FileSystemAccessRule(id, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        Directory.SetAccessControl(root, sec);
    }
    static byte[] Core() {
        using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("core.gz")) {
            if (s == null) throw new Exception("Falta el motor integrado del lanzador.");
            using (var gz = new GZipStream(s, CompressionMode.Decompress)) using (var m = new MemoryStream()) { gz.CopyTo(m); var b = m.ToArray(); if (Hash(b) != CoreSha) throw new Exception("Fallo de integridad del motor. No se ejecuta codigo alterado."); return b; }
        }
    }
    static string PackedCore() {
        Core(); using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("core.gz")) using (var m = new MemoryStream()) { s.CopyTo(m); return Convert.ToBase64String(m.ToArray()); }
    }
    static string NodePath() {
        var paths = new List<string>();
        foreach (string k in new[] { "ProgramW6432", "ProgramFiles", "ProgramFiles(x86)" }) { var p = Environment.GetEnvironmentVariable(k); if (!String.IsNullOrWhiteSpace(p)) paths.Add(Path.Combine(p, "nodejs", "node.exe")); }
        foreach (var p in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';')) { try { var q = p.Trim().Trim('"'); if (Path.IsPathRooted(q)) paths.Add(Path.Combine(q, "node.exe")); } catch { } }
        var found = paths.FirstOrDefault(File.Exists); if (found == null) throw new Exception("No se encontro Node.js instalado. No se descarga ni instala software automaticamente."); return found;
    }
    internal static string Quote(string arg) {
        if (arg == null) return "\"\"";
        var b = new StringBuilder("\""); int slash = 0;
        foreach (char c in arg) { if (c == '\\') { slash++; continue; } if (c == '"') { b.Append('\\', slash * 2 + 1); b.Append(c); slash = 0; continue; } b.Append('\\', slash); slash = 0; b.Append(c); }
        b.Append('\\', slash * 2); b.Append('"'); return b.ToString();
    }
    internal static int Execute(string root, string[] args, Action<string> update) {
        bool failed = false, ready = false; string failure = null, failureCode = null;
        var js = "eval(require('node:zlib').gunzipSync(Buffer.from('" + PackedCore() + "','base64')).toString('utf8'))";
        var opts = new { stateRoot = root, hostExe = Assembly.GetExecutingAssembly().Location, noOpen = args.Contains("--no-open") || args.Contains("--check-only"), checkOnly = args.Contains("--check-only"), reuse = args.Contains("--reuse"), allowLegacyStop = args.Contains("--allow-legacy-stop") };
        var info = new ProcessStartInfo(NodePath(), "--eval " + Quote(js) + " -- " + Quote(Convert.ToBase64String(Encoding.UTF8.GetBytes(Serializer().Serialize(opts))))) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8, WorkingDirectory = root };
        if (info.Arguments.Length > 28000) throw new Exception("El motor excede el limite de arranque de Windows.");
        info.EnvironmentVariables.Remove("NODE_OPTIONS"); info.EnvironmentVariables.Remove("NODE_PATH"); info.EnvironmentVariables["DSH_LAUNCHER_RUN"] = "1";
        using (var p = new Process { StartInfo = info }) {
            p.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                if (String.IsNullOrWhiteSpace(e.Data)) return;
                try {
                    var d = Serializer().Deserialize<Dictionary<string, object>>(e.Data); string ev = Text(d, "event");
                    update(Text(d, "message"));
                    if (ev == "failed") { failed = true; failure = Text(d, "message"); failureCode = Text(d,"code"); update("Codigo: " + Text(d,"code") + " | Diagnostico: " + Text(d,"report")); }
                    if (ev == "ready") {
                        ready = true; var summary = d.ContainsKey("summary") ? d["summary"] as Dictionary<string, object> : null;
                        if (summary != null) update("Perfil: " + Text(summary,"profile") + " | PID: " + Text(summary,"pid") + " | HTTP 303 -> 200 | " + Text(summary,"action"));
                        if (!args.Contains("--headless") && !args.Contains("--check-only")) InstallShortcut(root, update);
                        string u = Text(d, "url");
                        if (!String.IsNullOrEmpty(u)) {
                            Uri uri; if (!Uri.TryCreate(u, UriKind.Absolute, out uri) || uri.Scheme != "http" || uri.Host != "127.0.0.1" || uri.AbsolutePath != "/" || !String.IsNullOrEmpty(uri.UserInfo) || !uri.Query.StartsWith("?token=")) throw new Exception("URL de apertura no valida.");
                            try { Process.Start(new ProcessStartInfo(u) { UseShellExecute = true }); update("Acceso autenticado enviado al navegador. Token no mostrado."); }
                            catch { failed = true; failure = "DSH esta listo, pero Windows no pudo abrir el navegador predeterminado."; update(failure); }
                        }
                    }
                } catch (Exception x) { failed = true; failure = "Respuesta no valida del lanzador: " + x.GetType().Name; update(failure); }
            };
            p.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (!String.IsNullOrWhiteSpace(e.Data)) { failed = true; failure = "Error del motor Node. Revise state/last-result.json."; update(failure); } };
            p.Start(); p.BeginOutputReadLine(); p.BeginErrorReadLine();
            if (!p.WaitForExit(720000)) { try { p.Kill(); } catch { } throw new Exception("El verificador excedio su tiempo. No se termino el servidor DSH."); }
            p.WaitForExit();
            int code = p.ExitCode;
            if(code!=0||failed||!ready) {
                if(!args.Contains("--headless")&&failureCode=="IDENTITY_PERMISSION"&&!args.Contains("--elevated")) {
                    update("Windows solicitara permiso para identificar el DSH elevado; no se trata de un puerto ajeno.");
                    return 42;
                }
                if(!args.Contains("--headless")&&failureCode=="LEGACY_RESTART_CONFIRMATION"&&!args.Contains("--allow-legacy-stop")) {
                    var choice=MessageBox.Show("Este DSH se abrio fuera del nuevo lanzador. Se comprobaron los chats y no hay turnos activos. Para adoptar el cierre ordenado hay que terminar solo ese proceso anterior UNA vez. Los chats guardados permanecen; trabajos externos o datos que existan solo en memoria no estan garantizados.\n\nConfirmar esta transicion?",Title,MessageBoxButtons.YesNo,MessageBoxIcon.Warning);
                    if(choice==DialogResult.Yes)return Execute(root,args.Concat(new[]{"--allow-legacy-stop"}).ToArray(),update);
                }
                update(failure??"No se confirmo el reinicio. No se borro ni restauro el historial.");return 1;
            }
            return 0;
        }
    }
    static void InstallShortcut(string root, Action<string> update) {
        string target = Environment.GetEnvironmentVariable("DSH_LAUNCHER_INSTALLED");
        if (String.IsNullOrWhiteSpace(target)) {
            string own = Assembly.GetExecutingAssembly().Location;
            byte[] bytes = File.ReadAllBytes(own);
            string bin = Path.Combine(root, "bin"), version = Path.Combine(bin, Hash(bytes));
            foreach (string dir in new[] { bin, version }) {
                if (Directory.Exists(dir) && (File.GetAttributes(dir) & FileAttributes.ReparsePoint) != 0) throw new Exception("La carpeta del lanzador no puede ser un enlace.");
                Directory.CreateDirectory(dir);
            }
            target = Path.Combine(version, "DSH_REINICIAR.exe");
            if (!File.Exists(target)) { File.Copy(own, target, false); File.SetAttributes(target, File.GetAttributes(target) | FileAttributes.ReadOnly); }
            if (Hash(File.ReadAllBytes(target)) != Hash(bytes)) throw new Exception("La copia instalada del lanzador no coincide con esta version.");
        }
        if (String.IsNullOrWhiteSpace(target) || !File.Exists(target) || !Path.GetFullPath(target).StartsWith(Path.GetFullPath(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) return;
        object shell = null, link = null;
        try {
            string dest = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Reiniciar DSH.lnk");
            if (File.Exists(dest)) return;
            var t = Type.GetTypeFromProgID("WScript.Shell"); if (t == null) return;
            shell = Activator.CreateInstance(t);
            link = t.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { dest });
            var lt = link.GetType();
            lt.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { target });
            lt.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { root });
            lt.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "Reiniciar DSH con su perfil actual conservando los chats" });
            lt.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, new object[0]);
            update("Acceso directo creado: Reiniciar DSH, en el escritorio.");
        } catch { update("DSH esta listo; el acceso directo no pudo crearse. Conserva el ejecutable descargado."); }
        finally { if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link); if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell); }
    }
    static int SelfTest() {
        Core();
        foreach (var s in new[] { "", "simple", "C:\\Program Files\\nodejs\\node.exe", "a\"b", "a b\\", "C:\\Users\\HFRC\\" }) {
            var a = Native.Arguments("test.exe " + Quote(s)); if (a.Length != 2 || a[1] != s) throw new Exception("SELF_TEST_QUOTING_FAILED");
        }
        Console.WriteLine(Serializer().Serialize(new {status="SELF_TEST_OK",coreSha256=CoreSha,version="1.1.1",argumentTests=6}));return 0;
    }
}
internal sealed class LaunchForm : Form {
    readonly TextBox log = new TextBox(); readonly Label status = new Label(); bool working = true;
    public int ExitCode = 1;
    internal LaunchForm(string root, string[] args) {
        Text = Program.Title; Size = new Size(740, 380); MinimumSize = Size; StartPosition = FormStartPosition.CenterScreen; Font = new Font("Segoe UI", 10); BackColor = Color.White;
        var title = new Label { Text = "DSH  |  Reiniciar tu entorno", Font = new Font("Segoe UI", 18, FontStyle.Bold), AutoSize = true, Left = 24, Top = 20 };
        status.SetBounds(24, 64, 680, 40); status.Text = "Comprobando el perfil para un reinicio controlado...";
        log.SetBounds(24, 112, 680, 164); log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical; log.BorderStyle = BorderStyle.FixedSingle;
        var diag = new Button { Text = "Ver diagnostico", Left = 24, Top = 290, Width = 140, Height = 34 };
        diag.Click += delegate { string p=Path.Combine(root,"state","last-result.json"); if(File.Exists(p))Process.Start(new ProcessStartInfo("notepad.exe", Program.Quote(p)) {UseShellExecute=false}); };
        var hide = new Button { Text = "Ocultar", Left=564, Top=290, Width=140, Height=34 }; hide.Click += delegate { if(working)Hide();else Close(); };
        Controls.AddRange(new Control[] {title,status,log,diag,hide});
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if(working){e.Cancel=true;Hide();} };
        Shown += delegate {
            Task.Factory.StartNew(delegate {
                int result; try { result=Program.Execute(root,args,Post); }catch(Exception e){Post(e.Message);result=1;}
                BeginInvoke((Action)delegate { working=false;ExitCode=result;status.Text=result==0?"DSH disponible. Perfil y chats verificados.":result==42?"Windows solicitara permiso para continuar.":"No se confirmo el reinicio. El diagnostico indica la causa.";hide.Text="Cerrar"; if(result==0||result==42){var timer=new System.Windows.Forms.Timer{Interval=1800};timer.Tick+=delegate{timer.Stop();timer.Dispose();Close();};timer.Start();}else{Show();Activate();} });
            });
        };
    }
    void Post(string message) { if(IsDisposed)return;BeginInvoke((Action)delegate{if(!IsDisposed){status.Text=message;log.AppendText(message+Environment.NewLine);}}); }
}
internal static class Native {
    [DllImport("shell32.dll",SetLastError=true)] static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)]string s,out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr FindWindow(string cls,string name);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int n);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("iphlpapi.dll",SetLastError=true)] static extern uint GetExtendedTcpTable(IntPtr table,ref int size,bool sort,int family,int tableClass,uint reserved);
    [StructLayout(LayoutKind.Sequential)] struct Tcp4 { public uint state, localAddr, localPort, remoteAddr, remotePort, pid; }
    [StructLayout(LayoutKind.Sequential)] struct Tcp6 { [MarshalAs(UnmanagedType.ByValArray,SizeConst=16)] public byte[] localAddr; public uint localScope,localPort; [MarshalAs(UnmanagedType.ByValArray,SizeConst=16)] public byte[] remoteAddr; public uint remoteScope,remotePort,state,pid; }
    internal static void Activate(string name) { var h=FindWindow(null,name);if(h!=IntPtr.Zero){ShowWindow(h,9);SetForegroundWindow(h);} }
    internal static string[] Arguments(string s) { int n;var p=CommandLineToArgvW(s,out n);if(p==IntPtr.Zero)return new string[0];try{var a=new string[n];for(int i=0;i<n;i++)a[i]=Marshal.PtrToStringUni(Marshal.ReadIntPtr(p,i*IntPtr.Size));return a;}finally{LocalFree(p);} }
    static string Flag(string[] a,string key) { for(int i=0;i<a.Length;i++){if(a[i]==key&&i+1<a.Length)return a[i+1];if(a[i].StartsWith(key+"=",StringComparison.Ordinal))return a[i].Substring(key.Length+1);}return ""; }
    static bool Eq(string a,string b){try{return String.Equals(Path.GetFullPath(a),Path.GetFullPath(b),StringComparison.OrdinalIgnoreCase);}catch{return false;}}
    static List<Dictionary<string,object>> Listeners(int wanted) {
        var list=new List<Dictionary<string,object>>();
        foreach(int family in new[]{2,23}) {
            int size=0;uint code=GetExtendedTcpTable(IntPtr.Zero,ref size,true,family,3,0);
            if(code!=122&&code!=0)throw new Exception("No se pudo consultar la tabla TCP de Windows.");
            IntPtr p=Marshal.AllocHGlobal(size);
            try {
                code=GetExtendedTcpTable(p,ref size,true,family,3,0);if(code!=0)throw new Exception("La tabla TCP cambio; repita la comprobacion.");
                int n=Marshal.ReadInt32(p), step=family==2?Marshal.SizeOf(typeof(Tcp4)):Marshal.SizeOf(typeof(Tcp6));
                for(int i=0;i<n;i++) {
                    IntPtr r=IntPtr.Add(p,4+i*step);uint port,pid;string address;
                    if(family==2){var x=(Tcp4)Marshal.PtrToStructure(r,typeof(Tcp4));port=x.localPort;pid=x.pid;address=new IPAddress(x.localAddr).ToString();}
                    else{var x=(Tcp6)Marshal.PtrToStructure(r,typeof(Tcp6));port=x.localPort;pid=x.pid;address=new IPAddress(x.localAddr).ToString();}
                    var b=BitConverter.GetBytes(port);int value=(b[0]<<8)+b[1];if(value==wanted)list.Add(new Dictionary<string,object>{{"pid",(int)pid},{"address",address},{"port",value},{"expected",false}});
                }
            }finally{Marshal.FreeHGlobal(p);}
        }return list;
    }
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AttachConsole(uint pid);
    [DllImport("kernel32.dll")] static extern bool FreeConsole();
    [DllImport("kernel32.dll")] static extern uint GetConsoleProcessList([Out]uint[] ids,uint count);
    [DllImport("kernel32.dll")] static extern bool SetConsoleCtrlHandler(IntPtr handler,bool add);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GenerateConsoleCtrlEvent(uint code,uint group);
    static string ScriptArgument(string[] args) {
        for(int i=1;i<args.Length;i++) {
            string a=args[i];
            if(a=="--")return i+1<args.Length?args[i+1]:"";
            if(a=="--eval"||a=="-e"||a=="--print"||a=="-p"||a.StartsWith("--eval="))return "";
            if(a=="--import"||a=="--require"||a=="-r"||a=="--loader"||a=="--experimental-loader"||a=="--inspect-port"){i++;continue;}
            if(a.StartsWith("-"))continue;
            return a;
        }return "";
    }
    static string Creation(int pid,string fallback) {
        try{using(var p=Process.GetProcessById(pid))return p.StartTime.ToUniversalTime().ToString("o");}catch{return fallback;}
    }
    internal static object Request(Dictionary<string,object> q) {
        string op=Program.Text(q,"action");
        if(String.IsNullOrEmpty(op)||op=="probe")return Probe(q);
        if(op!="console-stop"&&op!="legacy-stop")throw new Exception("Operacion nativa no permitida.");
        int target=Convert.ToInt32(q["pid"]);string expectedCreation=Program.Text(q,"createdUtc");
        var inventory=Probe(q);
        var candidate=inventory.Processes.FirstOrDefault(x=>Convert.ToInt32(x["pid"])==target);
        if(candidate==null||Program.Text(candidate,"createdUtc")!=expectedCreation)throw new Exception("La identidad cambio antes del cierre.");
        using(var proc=Process.GetProcessById(target)) {
            IntPtr stableHandle=proc.Handle;
            if(proc.StartTime.ToUniversalTime().ToString("o")!=expectedCreation)throw new Exception("PID reutilizado: no se cierra.");
            if(op=="legacy-stop") {
                if(!q.ContainsKey("consent")||!(q["consent"] is bool)||(bool)q["consent"]!=true)throw new Exception("Falta consentimiento para la transicion del DSH anterior.");
                proc.Kill();return new {sent=true,method="LEGACY_EXPLICIT_TARGET_ONLY",pid=target};
            }
            FreeConsole();
            if(!AttachConsole((uint)target))return new {sent=false,reason="NO_PRIVATE_CONSOLE",pid=target};
            try {
                var ids=new uint[128];uint count=GetConsoleProcessList(ids,(uint)ids.Length);
                uint own=(uint)Process.GetCurrentProcess().Id;
                if(count==0||count>ids.Length||ids.Take((int)count).Any(id=>id!=own&&id!=(uint)target))return new {sent=false,reason="CONSOLE_SHARED",pid=target};
                SetConsoleCtrlHandler(IntPtr.Zero,true);
                if(!GenerateConsoleCtrlEvent(0,0))return new {sent=false,reason="CTRL_C_UNAVAILABLE",pid=target};
                Thread.Sleep(100);return new {sent=true,reason="CTRL_C_SENT",pid=target};
            }finally{FreeConsole();SetConsoleCtrlHandler(IntPtr.Zero,false);}
        }
    }
    internal sealed class ProbeResult {
        public List<Dictionary<string,object>> listeners;
        public List<Dictionary<string,object>> processes;
        public bool inspectorElevated;
        [ScriptIgnore] public List<Dictionary<string,object>> Processes {get{return processes;}}
    }
    internal static ProbeResult Probe(Dictionary<string,object> request) {
        string entry=Program.Text(request,"entry"),profile=Program.Text(request,"profile"),node=Program.Text(request,"nodeExe");int port=Convert.ToInt32(request["port"]);
        var listeners=Listeners(port);var processes=new List<Dictionary<string,object>>();
        var pids=new HashSet<int>(listeners.Select(x=>Convert.ToInt32(x["pid"])));
        var query="SELECT ProcessId, Name, ExecutablePath, CreationDate, CommandLine FROM Win32_Process WHERE Name = 'node.exe'";
        foreach(int pid in pids)query+=" OR ProcessId = "+pid;
        var seen=new HashSet<int>();
        using(var search=new ManagementObjectSearcher(query)) {
            search.Options.Timeout=TimeSpan.FromSeconds(10);
            foreach(ManagementObject p in search.Get())using(p) {
                int pid=Convert.ToInt32(p["ProcessId"]);seen.Add(pid);
                string cmd=Convert.ToString(p["CommandLine"]),exe=Convert.ToString(p["ExecutablePath"]),name=Convert.ToString(p["Name"]);
                bool unreadable=String.Equals(name,"node.exe",StringComparison.OrdinalIgnoreCase)&&(String.IsNullOrWhiteSpace(cmd)||String.IsNullOrWhiteSpace(exe));
                var args=String.IsNullOrEmpty(cmd)?new string[0]:Arguments(cmd);
                bool script=Eq(ScriptArgument(args),entry),nodeMatch=Eq(exe,node),profileMatch=Flag(args,"--profile")==profile,portMatch=Flag(args,"--port")==port.ToString();
                bool expected=script&&nodeMatch&&profileMatch&&portMatch;
                string created="";try{created=Creation(pid,ManagementDateTimeConverter.ToDateTime(Convert.ToString(p["CreationDate"])).ToUniversalTime().ToString("o"));}catch{}
                if(expected)processes.Add(new Dictionary<string,object>{{"pid",pid},{"createdUtc",created},{"expected",true}});
                foreach(var l in listeners.Where(x=>Convert.ToInt32(x["pid"])==pid)){
                    l["createdUtc"]=created;l["expected"]=expected&&Convert.ToString(l["address"])=="127.0.0.1";
                    l["reason"]=unreadable?"identity_unreadable":expected?"verified_dsh":!nodeMatch?"node_path_mismatch":!script?"entry_mismatch":!profileMatch?"profile_mismatch":"port_argument_mismatch";
                    l["processName"]=name;
                }
            }
        }
        foreach(var l in listeners.Where(x=>!seen.Contains(Convert.ToInt32(x["pid"]))))l["reason"]="identity_unreadable";
        return new ProbeResult{listeners=listeners,processes=processes,inspectorElevated=new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)};
    }
}
