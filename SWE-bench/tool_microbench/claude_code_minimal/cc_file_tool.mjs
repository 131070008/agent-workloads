#!/usr/bin/env node

import { readFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import {
  editTool,
  fullReadState,
  readTool,
  writeTool,
} from './cc_tool_microbench.mjs'

function usage() {
  return `Usage:
  cc_file_tool.mjs read  --file FILE [--offset LINE] [--limit LINES]
  cc_file_tool.mjs write --file FILE --content-file FILE
  cc_file_tool.mjs edit  --file FILE --old-file FILE --new-file FILE [--replace-all]
`
}

function parse(argv) {
  if (argv.length === 0 || argv.includes('--help') || argv.includes('-h')) {
    return { help: true }
  }
  const result = { command: argv[0], replaceAll: false }
  for (let index = 1; index < argv.length; index += 1) {
    const item = argv[index]
    if (item === '--file') result.file = argv[++index]
    else if (item === '--offset') result.offset = Number(argv[++index])
    else if (item === '--limit') result.limit = Number(argv[++index])
    else if (item === '--content-file') result.contentFile = argv[++index]
    else if (item === '--old-file') result.oldFile = argv[++index]
    else if (item === '--new-file') result.newFile = argv[++index]
    else if (item === '--replace-all') result.replaceAll = true
    else throw new Error(`Unknown argument: ${item}`)
  }
  if (!['read', 'write', 'edit'].includes(result.command)) {
    throw new Error(`Unknown command: ${result.command}`)
  }
  if (!result.file) throw new Error('--file is required')
  result.file = path.resolve(result.file)
  if (result.offset !== undefined && (!Number.isInteger(result.offset) || result.offset < 0)) {
    throw new Error('--offset must be an integer >= 0')
  }
  if (result.limit !== undefined && (!Number.isInteger(result.limit) || result.limit < 1)) {
    throw new Error('--limit must be an integer >= 1')
  }
  return result
}

async function main() {
  const args = parse(process.argv.slice(2))
  if (args.help) {
    process.stdout.write(usage())
    return
  }

  if (args.command === 'read') {
    const result = await readTool(args.file, args.offset ?? 1, args.limit)
    process.stdout.write(`${result.rendered}\n`)
    return
  }

  if (args.command === 'write') {
    if (!args.contentFile) throw new Error('--content-file is required for write')
    const content = await readFile(path.resolve(args.contentFile), 'utf8')
    const result = writeTool(args.file, content)
    process.stdout.write(`${result.rendered}\n`)
    return
  }

  if (!args.oldFile || !args.newFile) {
    throw new Error('--old-file and --new-file are required for edit')
  }
  const [oldString, newString] = await Promise.all([
    readFile(path.resolve(args.oldFile), 'utf8'),
    readFile(path.resolve(args.newFile), 'utf8'),
  ])
  // Claude Code requires a prior complete Read before Edit. The direct
  // executable establishes that state immediately before the edit call.
  fullReadState(args.file)
  const result = editTool(args.file, oldString, newString, args.replaceAll)
  process.stdout.write(`${result.rendered}\n`)
}

main().catch(error => {
  console.error(error.stack || error.message)
  process.exitCode = 1
})
