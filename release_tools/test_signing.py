import copy
import tempfile
import unittest
from pathlib import Path
import signing

class SigningTests(unittest.TestCase):
    def setUp(self):
        self.good={'status':'Valid','signature_type':'Authenticode','algorithm':'1.2.840.113549.1.1.1','timestamp':True,'thumbprint':'A'*40,'subject':'CN=Publisher'}
    def test_unsigned_current_release_is_rejected(self):
        bad=dict(self.good,status='NotSigned')
        with self.assertRaises(ValueError):signing.require_trusted(bad)
    def test_ecc_and_catalog_only_and_missing_timestamp_are_rejected(self):
        for field,value in [('algorithm','1.2.840.10045.2.1'),('signature_type','Catalog'),('timestamp',False),('status','HashMismatch')]:
            with self.subTest(field=field),self.assertRaises(ValueError):signing.require_trusted(dict(self.good,**{field:value}))
    def test_valid_timestamped_embedded_rsa_is_accepted(self):
        self.assertEqual(signing.require_trusted(self.good),self.good)
    def test_missing_signer_stops_before_build(self):
        with self.assertRaises(ValueError):signing.sign_arguments({})
    def test_timestamp_and_sha256_are_required_by_command(self):
        args=signing.sign_arguments({'signtool':'signtool.exe','thumbprint':'A'*40,'timestamp_url':'http://timestamp.digicert.com'})
        self.assertEqual(args[:5],['signtool.exe','sign','/fd','SHA256','/td'])
        self.assertIn('/tr',args);self.assertIn('/sha1',args)
    def test_ambiguous_or_partial_signer_is_rejected(self):
        base={'signtool':'signtool.exe','timestamp_url':'http://timestamp.digicert.com'}
        for extra in [{'thumbprint':'bad'},{'dlib':'x.dll'},{'thumbprint':'A'*40,'dlib':'x.dll','metadata':'x.json'}]:
            with self.assertRaises(ValueError):signing.sign_arguments(dict(base,**extra))
    def test_packaging_cannot_mutate_or_omit_signed_dll(self):
        original={'folder/lib.dll':b'MZsigned'}
        with self.assertRaises(ValueError):signing.verify_payload({'folder/lib.dll':b'MZmodified'},original)
        with self.assertRaises(ValueError):signing.verify_payload({},original)
        with self.assertRaises(ValueError):signing.verify_payload(dict(original,**{'extra.pyd':b'MZunsigned'}),original)
        signing.verify_payload(original,original)
    def test_copy_for_signing_does_not_modify_installed_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'vendor.dll';original.write_bytes(b'MZunsigned')
            def fake_sign(path):path.write_bytes(b'MZsigned');return self.good
            toc,inventory=signing.stage_binaries([('pkg/vendor.dll',str(original),'BINARY')],root/'stage',fake_sign)
            self.assertEqual(original.read_bytes(),b'MZunsigned')
            self.assertEqual(Path(toc[0][1]).read_bytes(),b'MZsigned')
            self.assertEqual(inventory['pkg/vendor.dll'],b'MZsigned')
    def test_staging_rejects_escape_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'vendor.dll';p.write_bytes(b'MZunsigned')
            with self.assertRaises(ValueError):signing.stage_binaries([('../escape.dll',str(p),'BINARY')],Path(tmp)/'stage',lambda p:None)

if __name__=='__main__':unittest.main()
