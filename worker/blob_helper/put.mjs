import { readFile } from "node:fs/promises";
import { put } from "@vercel/blob";

const [, , pathname, localPath, contentType] = process.argv;
const body = await readFile(localPath);
const blob = await put(pathname, body, {
  access: "private",
  contentType,
  addRandomSuffix: false,
  allowOverwrite: true,
  token: process.env.BLOB_READ_WRITE_TOKEN,
});
process.stdout.write(JSON.stringify({ url: blob.url, pathname: blob.pathname }));
