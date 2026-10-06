;;; SPDX-License-Identifier: ISC

(define-module (json2dir core)
  #:use-module (ice-9 format)
  #:use-module (ice-9 binary-ports)
  #:use-module (rnrs bytevectors)
  #:use-module (json2dir json)
  #:export (parse-and-run main))

(define (fail message . args)
  (throw 'json2dir-error (apply format #f message args)))

(define (io-attempt message thunk)
  (catch 'system-error thunk
    (lambda (key . args)
      (fail "~a: ~a" message (strerror (system-error-errno (cons key args)))))))

(define (check-no-nul text message)
  ;; Some Guile filesystem calls truncate at NUL instead of reporting EINVAL.
  (when (string-index text #\nul)
    (fail "~a: path contained an unexpected NUL byte" message)))

(define (validate-name name context)
  ;; Rust Path::components ignores repeated separators, trailing separators,
  ;; and interior '.', but retains a leading '.' or root component.
  (let* ((parts (string-split name #\/))
         (rooted? (string-prefix? "/" name))
         (components
          (let loop ((parts parts) (first? #t) (result '()))
            (if (null? parts)
                (reverse result)
                (let ((part (car parts)))
                  (if (or (string-null? part)
                          (and (string=? part ".") (not first?)))
                      (loop (cdr parts) #f result)
                      (loop (cdr parts) #f (cons part result))))))))
    (cond
     ((and rooted? (null? components))
      (fail "the key ~s under ~s is a non-regular path component" name context))
     ((or rooted? (not (= (length components) 1)))
      (fail "the key ~s under ~s must have exactly one path component" name context))
     ((member (car components) '("." ".."))
      (fail "the key ~s under ~s is a non-regular path component" name context)))))

(define (write-content name content context kind)
  (check-no-nul name (format #f "couldn't create a ~a at ~s" kind context))
  (io-attempt (format #f "couldn't create a ~a at ~s" kind context)
    (lambda ()
      (call-with-output-file name
        (lambda (port)
          (set-port-encoding! port "UTF-8")
          (set-port-conversion-strategy! port 'error)
          (display content port))))))

(define (write-directory name object context)
  (check-no-nul name (format #f "couldn't create a directory at ~s" context))
  (catch 'system-error
    (lambda () (mkdir name))
    (lambda (key . args)
      (let ((errno (system-error-errno (cons key args))))
        (unless (= errno EEXIST)
          (fail "couldn't create a directory at ~s: ~a" context (strerror errno))))))
  (io-attempt
   (format #f "couldn't set the current dir to the newly created path ~s" context)
   (lambda () (chdir name)))
  (write-object object context)
  (io-attempt
   (format #f "couldn't set the current dir ~s to the dir above it" context)
   (lambda () (chdir ".."))))

(define (write-array name value context)
  (unless (and (= (vector-length value) 2)
               (string? (vector-ref value 0))
               (string? (vector-ref value 1)))
    (fail "expected a JSON array to be of the form [type, payload] while at ~s" context))
  (let ((kind (vector-ref value 0)) (payload (vector-ref value 1)))
    (cond
     ((string=? kind "script")
      (write-content name payload context "script")
      (io-attempt (format #f "couldn't make the script executable at ~s" context)
        (lambda () (chmod name (logior (stat:perms (stat name)) #o111)))))
     ((string=? kind "link")
      (check-no-nul name (format #f "couldn't create a symlink at ~s" context))
      (check-no-nul payload (format #f "couldn't create a symlink at ~s" context))
      (io-attempt (format #f "couldn't create a symlink at ~s" context)
        (lambda () (symlink payload name))))
     (else
      (fail "expected a JSON array's first element to be either \"link\" or \"script\" while at ~s"
            context)))))

(define (write-object object context)
  (for-each
   (lambda (entry)
     (let ((name (car entry)) (value (cdr entry)))
       (validate-name name context)
       (let ((path (string-append context "/" name)))
         ;; unlink replaces files and even dangling symlinks, but leaves real
         ;; directories intact. Ignore unlink failures, as the Rust version does.
         (unless (string-index name #\nul)
           (catch 'system-error
             (lambda () (delete-file name))
             (lambda args #f)))
         (cond
          ((json-object? value) (write-directory name value path))
          ((string? value) (write-content name value path "regular file"))
          ((vector? value) (write-array name value path))
          (else
           (fail "expected a JSON value to be an object, an array, or a string while at ~s"
                 path))))))
   (json-object-entries object)))

(define (parse-and-run text)
  "Materialize TEXT in the current directory, restoring cwd even on failure.
Filesystem changes before an error remain, matching the original CLI."
  (let ((object (catch 'json-invalid
                  (lambda () (parse-json text))
                  (lambda args (fail "couldn't convert stdin to JSON")))))
    (unless (json-object? object)
      (fail "expected provided JSON to be an object"))
    (let ((locale (setlocale LC_CTYPE)))
      (dynamic-wind
        ;; Filenames, link targets, and file contents all use UTF-8, even when
        ;; the caller's locale is C. Restore the library caller's locale too.
        (lambda () (setlocale LC_CTYPE "C.UTF-8"))
        (lambda ()
          (let ((start (getcwd)))
            (dynamic-wind
              (lambda () #t)
              (lambda () (write-object object "."))
              (lambda () (chdir start)))))
        (lambda () (setlocale LC_CTYPE locale))))))

(define (read-stdin)
  (catch #t
    (lambda ()
      ;; Decode bytes explicitly: textual Guile ports consume an initial BOM,
      ;; whereas the original JSON parser rejects it.
      (utf8->string (get-bytevector-all (current-input-port))))
    (lambda args
      (fail "couldn't read stdin to an internal representation"))))

(define (main args)
  (set-port-encoding! (current-error-port) "UTF-8")
  (if (not (= (length args) 1))
      (begin
        (display "Usage: json2dir < file.json\n" (current-error-port))
        1)
      (catch 'json2dir-error
        (lambda () (parse-and-run (read-stdin)) 0)
        (lambda (_ message)
          (format (current-error-port) "Error: ~a.\n" message)
          1))))
