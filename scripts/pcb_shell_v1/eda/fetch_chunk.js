// 分块取回 export_file.js 缓存的文件内容（base64）。
const n = __CLI__.args.n, size = 6000000, s = globalThis.__gm_blob;
if (!s) throw new Error('没有缓存的文件');
return {chunk: s.slice(n * size, (n + 1) * size), done: (n + 1) * size >= s.length};
