// Getting a folder out of the browser — the two places it tries to lose the tree.
//
// 1. A dropped directory is NOT in `dataTransfer.files`. That list is empty for a folder; the
//    entries live behind `dataTransfer.items[i].webkitGetAsEntry()` and have to be walked.
// 2. `File.webkitRelativePath` is populated by a directory <input>, but it is NOT transmitted over
//    multipart — the browser sends `file.name` alone. So the paths travel as a parallel form field
//    and the server pairs them by position.
//
// Without both, `TA #1/BQ/BQ.pdf` and `TA #2/BQ/BQ.pdf` arrive as two files called `BQ.pdf` and the
// second overwrites the first on disk.

/** A file plus where it sat in the tree the user picked. */
export interface PickedFile {
  file: File;
  /** Always with forward slashes, never leading — e.g. `ND202504/TA #2/BQ/bill.xlsx`. */
  path: string;
}

const clean = (path: string): string => path.replace(/\\/g, "/").replace(/^\/+/, "");

/** Files from an `<input webkitdirectory>`, keeping each one's relative path. */
export function fromInput(files: FileList | null): PickedFile[] {
  return [...(files ?? [])].map((file) => ({
    file,
    // webkitRelativePath is "" for a plain multi-file pick; the name is then the whole path.
    path: clean((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name),
  }));
}

/**
 * Files from a drop, descending into any directories.
 *
 * Returns `null` when the drop contained no directory at all — the caller then treats it as an
 * ordinary binder drop rather than silently switching the whole ingest to folder mode because
 * somebody dragged two loose PDFs.
 */
export async function fromDrop(transfer: DataTransfer | null): Promise<PickedFile[] | null> {
  const items = [...(transfer?.items ?? [])];
  const entries = items
    .map((item) => (item.kind === "file" ? webkitEntry(item) : null))
    .filter((entry): entry is FileSystemEntry => Boolean(entry));

  if (!entries.some((entry) => entry.isDirectory)) return null;

  const picked: PickedFile[] = [];
  for (const entry of entries) await walk(entry, "", picked);
  return picked;
}

function webkitEntry(item: DataTransferItem): FileSystemEntry | null {
  const get = (item as DataTransferItem & {
    webkitGetAsEntry?: () => FileSystemEntry | null;
  }).webkitGetAsEntry;
  return typeof get === "function" ? get.call(item) : null;
}

async function walk(entry: FileSystemEntry, prefix: string, out: PickedFile[]): Promise<void> {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;

  if (entry.isFile) {
    const file = await new Promise<File | null>((resolve) =>
      (entry as FileSystemFileEntry).file(resolve, () => resolve(null)),
    );
    // A file the browser refuses to read is skipped rather than allowed to abort the whole
    // folder — one unreadable item must not cost the other two hundred.
    if (file) out.push({ file, path: clean(path) });
    return;
  }

  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries returns at most ~100 per call and signals the end with an empty batch, so it
    // has to be drained in a loop. Reading it once silently truncates a large tender folder.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve) =>
        reader.readEntries(resolve, () => resolve([])),
      );
      if (!batch.length) break;
      for (const child of batch) await walk(child, path, out);
    }
  }
}

/** The folder everything shares, which is a far better project name than whichever PDF sorts first. */
export function commonRoot(picked: PickedFile[]): string {
  const roots = new Set(picked.map((p) => p.path.split("/")[0]).filter(Boolean));
  if (roots.size === 1) {
    const only = [...roots][0];
    // A single file picked on its own has no folder — its "root" is the filename.
    if (picked.some((p) => p.path.includes("/"))) return only;
  }
  return "";
}
