// PKWare DCL decoder subprocess. Input: raw imploded bytes on stdin.
// Output: raw bytes on stdout. Third-party algorithm is MIT licensed
// (see implode_decoder.LICENSE). No original game files are modified.
'use strict';
const decoder = require('./implode_decoder')();
decoder.on('error', err => {
  console.error(err.message);
  process.exitCode = 1;
});
process.stdin.pipe(decoder).pipe(process.stdout);
