"""Frame-specific display guard for the research review-card prototype."""
def visible_context(confirmed_frame_sha, frame_sha, checks):
 if confirmed_frame_sha is None:return []
 if not isinstance(confirmed_frame_sha,str) or len(confirmed_frame_sha)!=64:raise ValueError('Confirmation must identify one immutable frame SHA256')
 if confirmed_frame_sha!=frame_sha:return []
 return [c['box'] for c in checks if c.get('accepted') is True and c['box'].get('class_id') in [0,2]]
def check_guard():
 a='a'*64;b='b'*64
 checks=[{'accepted':True,'box':{'class_id':0}},{'accepted':False,'box':{'class_id':2}},{'accepted':True,'box':{'class_id':1}}]
 tests=[
 {'case':'unconfirmed_frame_hides_all_context','passed':visible_context(None,a,checks)==[]},
 {'case':'confirmation_does_not_transfer_to_another_frame','passed':visible_context(a,b,checks)==[]},
 {'case':'approved_frame_still_requires_verified_context_class','passed':visible_context(a,a,checks)==[{'class_id':0}]},
 {'case':'unverified_context_stays_hidden_after_confirmation','passed':visible_context(a,a,[{'accepted':False,'box':{'class_id':0}}])==[]}]
 assert all(t['passed'] for t in tests)
 return tests
