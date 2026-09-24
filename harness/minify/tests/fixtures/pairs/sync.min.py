def sync(record_id,opts=None):
 opts=opts or {}
 response=post(f"/api/{record_id}",timeout=opts.get("timeout",5))
 if not response.ok:raise RuntimeError(response.status)
 return{"id":record_id,"items":response.json().get("items",[])}
