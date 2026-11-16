"""Offline regression checks for video upload and exact-frame review policy."""
import tempfile
import unittest
from pathlib import Path
import video_review_workflow as w

class VideoWorkflowTests(unittest.TestCase):
    def test_upload_keeps_one_safe_file_and_never_overwrites_other_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            a=w.save_uploaded_video('../../same.mp4',b'first',root)
            b=w.save_uploaded_video('../../same.mp4',b'second',root)
            self.assertEqual(a.parent,root.resolve())
            self.assertNotEqual(a,b)
            self.assertEqual(a.read_bytes(),b'first')
            self.assertEqual(w.save_uploaded_video('../../same.mp4',b'first',root),a)
            for name,data in [('empty.mp4',b''),('wrong.txt',b'x'),('large.mp4',b'1234')]:
                with self.assertRaises(ValueError):w.save_uploaded_video(name,data,root,max_bytes=3)

    def test_negative_ai_never_discards_candidate_and_approval_stays_on_exact_index(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)
            original=run/'pixels.jpg';original.write_bytes(b'identical source pixels')
            image_sha=w.sha(original)
            frames=[]
            for i in range(2):
                frames.append(dict(frame_index=i,sample_index=i,source_seconds=float(i),sha256=image_sha,
                    frame_uid=w.frame_uid('video',i,image_sha),path=str(original),size=[100,100]))
            w.write(run/'manifest.json',{'config':{'start_seconds':0,'group_seconds':1},'frames':frames})
            animal={'x1':10,'y1':10,'x2':30,'y2':30,'class_id':1,'score':.8}
            person={'x1':40,'y1':10,'x2':50,'y2':40,'class_id':0,'score':.8}
            w.write(run/'dmd.json',[{'frame_uid':f['frame_uid'],'boxes':[animal]} for f in frames])
            w.write(run/'world.json',[{'frame_uid':f['frame_uid'],'boxes':[person]} for f in frames])
            for f in frames:
                review_input=run/'review-inputs'/f['frame_uid']/'whole.jpg'
                review_input.parent.mkdir(parents=True);review_input.write_bytes(b'prepared input')
                manifest={'frame_uid':f['frame_uid'],'images':[{'image_id':'F1-whole','path':str(review_input),'sha256':w.sha(review_input)}],
                    'context_regions':[{'region_id':'person-1','box':person}]}
                w.write(review_input.parent/'manifest.json',manifest)
                data={'frames':[{'frame_id':'F1','mammal_visible':'no','people_visible':'yes','vehicles_visible':'no',
                    'visible_mammal_features':'no clear mammal','evidence_image_ids':['F1-whole'],
                    'context_regions':[{'region_id':'person-1','proposed_class_present':'yes','evidence':'person torso'}]}]}
                w.write(run/'reviews'/(f['frame_uid']+'.json'),{'frame_uid':f['frame_uid'],'status':'success',
                    'image_sha256':[w.sha(review_input)],'data':data})
            cards=w.build_cards(run)
            self.assertTrue(all(c['candidate_retained'] for c in cards))
            self.assertEqual([c['shown_context_regions'] for c in cards],[0,0])
            w.approve(run,frames[0]['frame_uid'],'yes')
            self.assertEqual([c['shown_context_regions'] for c in w.build_cards(run)],[1,0])
            w.approve(run,frames[0]['frame_uid'],'uncertain')
            self.assertEqual([c['shown_context_regions'] for c in w.build_cards(run)],[0,0])
            w.approve(run,frames[0]['frame_uid'],'yes')
            (run/'review-inputs'/frames[0]['frame_uid']/'whole.jpg').write_bytes(b'changed input')
            self.assertEqual(w.build_cards(run)[0]['shown_context_regions'],0)
            with self.assertRaises(ValueError):w.approve(run,'wrong-frame','yes')

    def test_guard_rejects_cross_frame_evidence_and_non_context_classes(self):
        self.assertTrue(w.self_check().startswith('PASS:'))

if __name__=='__main__':unittest.main()
