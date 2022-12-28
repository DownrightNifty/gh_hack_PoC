import subprocess

# if protoc is not in PATH, replace with its location
PROTOC_FN = 'protoc'

# ensure protoc is available before loading module (raises FileNotFoundError)
subprocess.run([PROTOC_FN], capture_output=True)

class ProtocError(Exception):
    """Raised if protoc returns a non-zero status code."""
    pass

def _raise_on_err(c):
    """
    Takes a subprocess.CompletedProcess from running protoc and raises an
    appropriate error if it failed.
    """
    if c.returncode != 0:
        err_msg = c.stderr.decode('utf-8').strip()
        raise ProtocError(f'protoc returned non-zero: {err_msg}')

def decode_raw(pb_data):
    """
    Decodes the binary protobuf data into protobuf text format.
    """
    c = subprocess.run([PROTOC_FN, '--decode_raw'], input=pb_data,
                       capture_output=True)
    _raise_on_err(c)
    pb_text = c.stdout.decode('utf-8')
    return pb_text

def encode(pb_text, proto_fn, proto_msg):
    """
    Encodes the pb_text (protobuf text format) into binary protobuf data using
    the message proto_msg from the proto file at proto_fn.
    """
    c = subprocess.run([PROTOC_FN, f'--encode={proto_msg}', proto_fn],
                       input=pb_text.encode('utf-8'), capture_output=True)
    _raise_on_err(c)
    pb_data = c.stdout
    return pb_data