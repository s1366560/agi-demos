(module
  (memory (export "memory") 2)
  (data (i32.const 65536) "{\"ok\":true,\"op\":\"ping\"}")
  (func (export "invoke") (param $len i32) (result i32)
    (if (result i32) (i32.eqz (local.get $len))
      (then (i32.const 0))
      (else (i32.const 23)))))
