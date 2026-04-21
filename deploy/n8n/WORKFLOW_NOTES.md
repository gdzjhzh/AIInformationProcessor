# n8n 閹恒儱鍙嗙憰浣哄仯

瑜版挸澧犳禒鎾崇氨閹?`Obsidian 娑撹绨盽 濡€崇础閹笛嗩攽閵嗕糠8n 閸欘亣绀嬬拹锝囩椽閹烘帪绱濇稉宥呯安鐠囥儳鎴风紒顓熺川閸欐ɑ鍨氬▽鈩冩箒濞村鐦潏鍦櫕閻ㄥ嫪绗熼崝鈥插敩閻椒绮ㄩ妴鍌氭倵缂侇厽澧嶉張澶婂弳閸欙綁鍏橀崗鍫熸暪閸欙絾鍨氱紒鐔剁鐎电钖勯敍灞藉晙婢跺秶鏁ゆ稉璇插叡閼哄倻鍋ｉ柧鎹愮熅閵?

## 娑撹鍏遍崢鐔峰灟

- 閸忋儱褰涢柅鍌炲帳閸ｃ劌褰х拹鐔荤煑閹跺﹤顦婚柈銊ュ敶鐎圭娴嗛幑銏″灇 `NormalizedTextObject`閵?
- Obsidian 閸愭瑥鍙嗛崳銊ュ涧娣囨繄鏆€娑撯偓婵?frontmatter 閸滃苯鎳￠崥宥堫潐閸掓瑣鈧?
- `AI enrich`閵嗕梗Qdrant gate`閵嗕梗Vault writer` 韫囧懘銆忛懗鍊燁潶婢舵矮閲滈崗銉ュ經婢跺秶鏁ら妴?
- `Memos` 閺勵垱鏁捄顖ょ礉娑撳秵妲?n8n 娑撹鍏辨潻鎰攽娓氭繆绂嗛妴?
- 闁氨鐓℃稉搴″晸鎼存捁袙閼帮讣绱濋柆鍨帳閳ユ粌鍟撴惔鎾炽亼鐠愩儵妯嗘繅鐐衡偓姘辩叀閳ユ繃鍨ㄩ垾婊堚偓姘辩叀婢惰精瑙﹂梼璇差敚閽€钘夌氨閳ユ縿鈧?

## 瀹搞儰缍斿ù浣瑰閸?

### `00_common_normalize_text_object`

閼卞矁鐭楅敍姘Ω娴犵粯鍓伴崗銉ュ經缂佺喍绔撮弰鐘茬殸娑撹桨瀵岄獮鎻掝嚠鐠灺扳偓?

閺堚偓鐏忓繗绶崙鍝勭摟濞堢绱?

```json
{
  "item_id": "stable-hash",
  "source_type": "rss",
  "source_name": "OpenAI YouTube",
  "original_id": "platform-item-id",
  "canonical_url": "https://example.com/post",
  "title": "Post title",
  "author": "Author",
  "published_at": "2026-04-17T09:00:00-04:00",
  "ingested_at": "2026-04-17T09:05:00-04:00",
  "media_type": "text",
  "content_text": "normalized plain text",
  "content_html": "<p>optional</p>",
  "upstream_task_id": "",
  "upstream_view_token": "",
  "upstream_summary": "",
  "content_hash": "sha256:...",
  "score": 0,
  "category": "pending",
  "tags": [],
  "dedupe_action": "full_push",
  "status": "raw",
  "vault_path": ""
}
```

缁撅附娼敍?

- `item_id` 娴兼ê鍘涢悽?`canonical_url` 閹?`source_type + original_id` 閻㈢喐鍨氶妴?
- `content_text` 閺勵垰鎮楃紒顓＄槑閸掑棎鈧焦鎲崇憰浣碘偓涔猰bedding 閸烆垯绔存稉缁樻瀮閺堫兙鈧?
- `vault_path` 閻㈣京绮烘稉鈧?writer 閻㈢喐鍨氶敍灞肩瑝閸忎浇顔忛崥鍕弳閸欙綀鍤滅悰灞界暰娑斿褰熸稉鈧總妤€鎳￠崥宥冣偓?
- 閸忋儱褰涢柅鍌炲帳閸ｃ劌婀潻娑樺弳 `00_common_normalize_text_object` 娑斿澧犻崣顖欎簰閺嗗倹妞傞幐浣规箒 `obsidian_inbox_dir / raw_text / raw_html / transcript_text / calibrated_transcript` 鏉╂瑧琚€涙顔岄敍娑楃閺冿箒绶崙?`NormalizedTextObject`閿涘苯绻€妞よ崵绮烘稉鈧幎妯哄綌閹?`obsidianInboxDir / content_text / content_html`閵?
- 閺堝搫娅掗崣顖濐嚢婵傛垹瀹抽崶鍝勭暰閸?`contracts/normalized_text_object.schema.json`閿涘瞼銇氭笟瀣祼鐎规艾婀?`contracts/examples/*.normalized.json`閿涘瞼绮撶粩顖涚墡妤犲苯鎳℃禒銈嗘Ц `python contracts/validate_contract.py`閵?
- `source_host` 閻滄澘婀憴鍡曡礋娑撹鍏遍弽鍥у櫙鐎涙顔岄敍灞肩瑝閸愬秵妲?`00` 閸愬懘鍎存い鐑樺鐞涖儱鍤弶銉ょ稻閺傚洦銆傚▽鈩冩暪閸欙絿娈戦梾鎰儓鐎涙顔岄妴?
- `dedupe_action` 閺勵垯瀵岄獮鎻掓暜娑撯偓閸斻劋缍旂€涙顔岄崥宥忕幢閺傚洦銆傞妴浣恒仛娓氬鎷伴懘姘拱闁垝绗夋惔鏂垮晙娴ｈ法鏁ゅ▔娑樺閻?`action`閵?

### 1_rss_to_obsidian_raw

閼卞矁鐭楅敍姝奡S / YouTube XML / 閹绢厼顓归惃鍕瘜楠炴彃鍙嗛崣锝忕礉閸忓牏绮烘稉鈧€电钖勯敍灞藉晙閸嬫矮绌剁€规粌鍨介弬顓溾偓浣告倻闁插繐鍨甸崚銈冣偓浣瑰瘻闂団偓 LLM閵嗕胶绮烘稉鈧崘娆忕氨閸滃苯娆㈡潻鐔哄偍瀵洘褰佹禍銈冣偓?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Schedule Trigger
2. Feed Sources
3. RSS Feed Read
4. Build Normalize Input
5. IF route_to_transcript
6. 4_video_transcript_ingest閿涘牊鎸辩€?/ 闂婃娊顣堕崐娆撯偓澶涚礆閹?0_common_normalize_text_object閿涘牊娅橀柅姘瀮閺堫剨绱?7. 1a_rule_prefilter
8. 3_qdrant_gate
9. IF should_continue_to_llm
10. 2_enrich_with_llm
11. 4a_action_policy
12. 5_common_vault_writer
13. 3b_qdrant_commit

鐠囧瓨妲戦敍?
- 閺傚洦婀版稉鑽ゅ殠閻滄澘婀弰?0 -> 01a -> 03 -> [silent 閸掓瑧娲块幒銉ㄧ儲鏉?LLM] -> 02 -> 04a -> 05 -> 03b閵?- 4_video_transcript_ingest 娑撳秴鍟€閸︺劌鍞撮柈銊ф纯閹恒儱鍟?Vault閿涘矁鈧本妲告潻鏂挎礀閸氬奔绔存禒鎴掑瘜缁惧灝顕挒锛勭舶鐠嬪啰鏁ら懓鍛埛缂侇叀铔?5 -> 03b閵?- silent 韫囧懘銆忛惇鐔割劀鐠哄疇绻?LLM 娑撳骸鍟撴惔鎿勭幢diff_push 閸掓瑥绨查幎濠傚爱闁板秳绗傛稉瀣瀮閸愭瑥鍙?note閿涘奔绌舵禍搴㈢壋鐎电懓鐤勯梽鍛存閸ｎ亞绮ㄩ弸婧库偓?- Build Markdown 缂佈呯敾鐏炵偘绨?5_common_vault_writer 閸愬懘鍎撮懕宀冪煑閿涘奔绗夌憰浣筋唨閹芥顩﹂妴浣烘倞閻㈠崬鎷扮紒鎾寸€崠鏍槑閸掑棗浠犻悾娆忔躬娑撳瓨妞傞幍褑顢戦弫鐗堝祦闁插被鈧?### 2_enrich_with_llm

閼卞矁鐭楅敍姘辩埠娑撯偓閹笛嗩攽鐠囧嫬鍨庨妴浣稿瀻缁眹鈧焦鐖ｇ粵鎯ф嫲閹芥顩﹂敍灞肩稻閸欘亜婀?3_qdrant_gate 閸掋倕鐣鹃垾婊冣偓鐓庣繁缂佈呯敾閳ユ繂鎮楅幍宥堢殶閻劊鈧?
鏉堟挸鍙嗛敍姝歂ormalizedTextObject閿涘苯鑻熼崣顖炩偓澶嬫儭鐢?matched_payload / matched_score / dedupe_action 娴ｆ粈璐熼垾婊勬付鏉╂垿鍋︽稉濠佺瑓閺傚洠鈧縿鈧?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Execute Workflow Trigger 閹?Manual Trigger + Example Normalized Text Object
2. Validate Normalized Text Object
3. Build LLM Request
4. HTTP Request -> {{.LLM_BASE_URL}}/chat/completions
5. Parse And Merge Enrichment

鏉堟挸鍤憰浣圭湴閿涙瓈LM 鏉╂柨娲栭崶鍝勭暰 JSON schema閿涘苯鑻熺悰銉ュ晸閸掓澘鎮撴稉鈧€电钖勬稉濠忕窗

`json
{
  "score": 0.82,
  "category": "AI Infra",
  "tags": ["openai", "model-release"],
  "summary": "娑撯偓濞堝灚娓剁紒鍫熸喅鐟?,
  "reason": "娑撹桨绮堟稊鍫濃偓鐓庣繁娣囨繄鏆€閹存牠妾烽崳?
}
`

缁撅附娼敍?
- summary 閺勵垯瀵岄獮鍙夋付缂佸牊鎲崇憰渚婄礉娑撳秴鍟€娴犲骸鍩嗘径鍕槻閸掑墎顑囨禍灞煎敜閹芥顩︾€涙顔岄妴?- Video Transcript API 閼汇儰绗傚〒绋垮嚒鏉╂柨娲栭幗妯款洣閿涘苯褰ч崘娆忓弳 upstream_summary 娓氭稑寮懓鍐︹偓?- 瑜?matched_payload 鐎涙ê婀弮璁圭礉
ovelty 娑撳秴绨查崣顏堟浆濡€崇€烽懛顏嗘暠閸欐垶灏岄敍娑樼安閹跺﹥娓舵潻鎴﹀仸閹芥顩﹂崪宀€娴夋导鐓庡娑撯偓鐠у嘲鏉虹紒?LLM 閸嬫艾妯婂鍌氬灲閺傤厹鈧?- 閸氬奔绔撮弶鈥愁嚠鐠炩€冲涧閺囧瓨鏌婇崥灞肩娴?frontmatter 閸滃本顒滈弬鍥风礉娑撳秴鍟€娴溠冨毉缁楊兛绨╃粔?note 缂佹挻鐎妴?- 鐞?1_rss_to_obsidian_raw 鐠嬪啰鏁ら弮璁圭礉鎼存棃鈧俺绻?Execute Workflow Trigger 閻╁瓨甯村☉鍫ｅ瀭娑撳﹥鐖?item閿涘奔绗夐崘宥夊櫢閺備即鈧姳绔存禒鐣屻仛娓氬顕挒掳鈧?- 娴ｆ粈璐?1 閻ㄥ嫬鐡欏銉ょ稊濞翠礁顕遍崗銉︽閿涘畭02_enrich_with_llm 韫囧懘銆忔径鍕艾閸欘垱澧界悰宀€濮搁幀渚婄礉閸氾箑鍨?Execute Workflow 娴兼氨娲块幒銉﹀Г Workflow is not active閵?- 瀹搞儰缍斿ù浣哥安閸︺劏鐨熼悽?LLM 娑斿澧犻弽锟犵崣 item_id / source_type / source_name / title / content_text 閸?LLM_BASE_URL / LLM_MODEL / LLM_API_KEY閵?- 閹恒劏宕樺▽璺ㄦ暏 OpenAI-compatible Chat Completions 閹恒儱褰涢敍灞借嫙閹?esponse_format 閸ュ搫鐣鹃幋?json_object閵?- 閸ョ偛鍟撶€电钖勯弮璺虹安閺傛澘顤?summary閵嗕梗reason閵嗕梗enriched_at閿涘苯鑻熼幎?status 閺囧瓨鏌婃稉?enriched閵?### 3_qdrant_gate

閼卞矁鐭楅敍姘躬 LLM 娑斿澧犻幍褑顢?embedding閵嗕浇绻庨柇缁樻偝缁便垹鎷扮划妤冪煈鎼达箑骞撻柌宥呭灲鐎规熬绱濋崣顏勫枀鐎规埃鈧粍妲搁崥锕€鈧厧绶辩紒褏鐢荤拫鍐暏 LLM閳ユ縿鈧?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Execute Workflow Trigger 閹?Manual Trigger + Example Enriched Item
2. Validate Gate Input
3. Build Embedding Request
4. HTTP Request -> {{.EMBEDDING_BASE_URL}}/embeddings
5. Build Qdrant Search Request
6. Qdrant Search -> http://qdrant:6333/collections/{collection}/points/search
7. Code: Decide Action
8. Return Gate Result

閸掋倕鐣剧憴鍕灟閿?
- < 0.85閿涙瓪full_push
- .85 ~ 0.97閿涙瓪diff_push
- > 0.97閿涙瓪silent

姒涙顓绘惔鏃堚偓姘崇箖閻滎垰顣ㄩ崣姗€鍣洪弰鎯х础閺€璺哄經娑撶尨绱?
- EMBEDDING_INPUT_MAX_CHARS=6000
- QDRANT_DIFF_THRESHOLD=0.85
- QDRANT_SILENT_THRESHOLD=0.97

缁撅附娼敍?
- EMBEDDING_MODEL 娑?QDRANT_VECTOR_SIZE 韫囧懘銆忕紒鎴濈暰閿涘奔绗夋惔鏃傛殌娑撯偓娑擃亞鈹栧Ο鈥崇€烽柊宥勭缂佸嫬鍟撳鑽ゆ樊鎼达负鈧?- EMBEDDING_INPUT_MAX_CHARS 鎼存柧缍旀稉?provider 閸忕厧顔愮仦鍌氬棘閺佸府绱濋懓灞肩瑝閺勵垳鎴风紒顓犫€栫紓鏍垳閸?workflow 闁插被鈧?- Qdrant 閸︺劋瀵岄獮鏌ュ櫡閺勵垰鍟撻崗銉ュ閸掋倕鐣鹃崳顭掔礉娑撳秵妲告禍瀣倵婢х偛宸辨禒韬测偓?- 3_qdrant_gate 閻ㄥ嫯绶崗銉у箛閸︺劍娼甸懛?1a_rule_prefilter閿涘本鐗宠箛鍐翻閸忋儱绨查弰?search_text閿涘奔绗夐崘宥勭贩鐠?2_enrich_with_llm 閸忓牅楠囬崙?summary閵?- 鏉╂瑤閲滈梼鑸殿唽閸欘亣绶崙?dedupe_action / matched_payload / matched_score / should_continue_to_llm 閸滃瞼鐭栫划鎺戝閻?should_write_to_vault / should_notify / should_upsert_qdrant閿涙稒娓剁紒鍫濆З娴ｆ粎鐓╅梼鐢垫暠 4a_action_policy 閺€璺哄經閵?- 閼汇儲娓舵潻鎴﹀仸閸涙垝鑵戦惃?payload.item_id 娑撳骸缍嬮崜宥咁嚠鐠烇紕娴夐崥宀嬬礉鐟曚礁鍘涢崠鍝勫瀻閳ユ粌鎮撴稉鈧弧鍥ㄦ瀮缁旂姴鍞寸€硅婀崣妯封偓婵呯瑢閳ユ粌鎮撴稉鈧弧鍥ㄦ瀮缁旂姵娲块弬棰佺啊閸愬懎顔愰垾婵撶窗
  - 閻╃鎮?content_hash閿涙瓪silent
  - 娑撳秴鎮?content_hash閿涙瓪diff_push
### 3b_qdrant_commit

閼卞矁鐭楅敍姘躬 5_common_vault_writer 閹存劕濮涢崘娆忕氨娑斿鎮楅敍灞剧€鐑樻付缂?Qdrant payload 楠炶埖褰佹禍銈囧偍瀵洏鈧?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Execute Workflow Trigger 閹?Manual Trigger + Example Written Item
2. Build Qdrant Commit Payload
3. IF should_commit_qdrant
4. Qdrant Upsert
5. Return Commit Result

鏉堝湱鏅痪锔芥将閿?
- 3b_qdrant_commit 韫囧懘銆忛崣鎴犳晸閸?ault_write_status=written 娑斿鎮楅敍娑橆洤閺?Vault 濞屸€冲晸閹存劧绱濈槐銏犵穿韫囧懘銆忔穱婵囧瘮閺堫亝褰佹禍銈囧Ц閹降鈧?- 鏉╂瑩鍣烽幍宥囨晸閹存劖娓剁紒?qdrant_point_id / qdrant_upsert_payload閿涘奔绗夌憰浣稿晙鐠?3_qdrant_gate 娑撯偓鏉堣鎮虫稉鈧潏鐟板櫙婢跺洦褰佹禍?payload閵?- 3b_qdrant_commit 閸欘亣绀嬬拹锝囧偍瀵洘褰佹禍銈忕礉娑撳秴鍟€閹垫寧濯寸拠鍕瀻閵嗕焦鎲崇憰浣瑰灗閸愭瑥绨辩拹锝勬崲閵?### 4_video_transcript_ingest

閼卞矁鐭楅敍姘Ω VideoTranscriptAPI 閹恒儲鍨氭稉鈧稉顏勵樆闁劌鍙嗛崣锝夆偓鍌炲帳閸ｎ煉绱濋懓灞肩瑝閺勵垱濡哥€瑰啴鍣搁崘娆掔箻 code node閵?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Webhook 閹存牗澧滈崝銊ㄐ曢崣?2. POST /api/transcribe
3. Poll /api/task/{id}
4. GET /view/{token}?raw=calibrated
5. 0_common_normalize_text_object
6. 1a_rule_prefilter
7. 3_qdrant_gate
8. IF should_continue_to_llm
9. 2_enrich_with_llm
10. 4a_action_policy
11. Return Mainline Result

鏉堝湱鏅痪锔芥将閿?
- VideoTranscriptAPI 鐠愮喕鐭楁稉瀣祰閵嗕浇娴嗚ぐ鏇樷偓浣圭墡鐎靛箍鈧?- 娑撹鍏辩拹鐔荤煑閹垫挸鍨庨妴浣稿瀻缁眹鈧焦鐖ｇ粵淇扁偓浣规付缂佸牊鎲崇憰渚婄幢閻喐顒滈惃?Vault 閸愭瑥鍙嗛悽杈殶閻劏鈧懎鍟€缂佺喍绔存禍銈囩舶 5_common_vault_writer閿涘奔绠ｉ崥搴″晙鐠?3b_qdrant_commit閵?- iew_token 閸欘亜浠涢崘鍛村劥鏉╁€熼嚋閿涘奔绗夐懗钘夌秼閸忣剙绱戦崚鍡楀絺闁剧偓甯撮妴?### 5_common_vault_writer

閼卞矁鐭楅敍姘彙娴?Obsidian 閸愭瑥鍙嗙仦鍌︾礉閸欘亝绉风拹鐟板嚒缂佸繗绻冩０鍕灲閸滃苯濮╂担婊呯摜閻ｃ儳娈戞稉鑽ゅ殠鐎电钖勯妴?
鏉堟挸鍙嗛敍姘冲殾鐏忔垵瀵橀崥?item_id / title / published_at / should_write_to_vault閿涘苯鑻熸导妯哄帥閹煎搫鐢?summary / reason / dedupe_action / notification_mode / matched_payload閵?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Execute Workflow Trigger 閹?Manual Trigger + Example Gate Result
2. Prepare Vault Write Context
3. IF should_write_to_vault
4. Build Markdown
5. Write Binary File
6. Return Vault Result

鏉堝湱鏅痪锔芥将閿?
- 5_common_vault_writer 閸愬懘鍎撮崣顏勵槱閻?skip / write / return status閿涘奔绗夐崘宥堢鐠?Qdrant upsert閵?- 閺傚洣娆㈤崨钘夋倳閵嗕公rontmatter閵嗕梗vault_path 閻㈢喐鍨氱憴鍕灟閸欘亙绻氶悾娆掔箹娑撯偓婵傛绱濋柆鍨帳 1 / 06 / 閸氬海鐢婚崗銉ュ經 閸愬秹鏆遍崙铏诡儑娴滃苯顨?note 缂佹挻鐎妴?- 缂佺喍绔存潻鏂挎礀 ault_path / vault_write_status閿涘苯鑻熸穱婵堟殌 ault_write 閸忕厧顔愮€涙顔岄敍灞肩返閺冄冨弳閸欙綁鈧劖顒炴潻浣盒╅妴?- should_write_to_vault=false 閺冭泛绻€妞ゆ槒绻戦崶?skipped閿涘矁鈧奔绗夐弰顖濐唨閸氬嫬鍙嗛崣锝堝殰鐞涘瞼瀹崇€规氨鈹栭崐鍏煎灗缂傚搫鐡у▓鐐光偓?- 閸愭瑥绨遍幋鎰閸氬氦瀚㈡禒宥夋付缁便垹绱╅敍灞界安閻㈣精鐨熼悽銊ㄢ偓鍛埛缂侇叀铔?3b_qdrant_commit閿涘矂浼╅崗?writer 闁插秵鏌婇崣妯诲灇鐟欏嫬鍨鏇熸惛閸旂姷鍌ㄥ鏇炴珤閻ㄥ嫭璐╅崥鍫濈湴閵?### 6_manual_media_submit

閼卞矁鐭楅敍姘拱閸︾増澧滈崝銊﹀闁帒鐛熸担?URL閿涘苯褰х拹鐔荤煑閹?YouTube / 閹绢厼顓?/ 閸忔湹绮棅瀹狀潒妫版垿鎽奸幒銉﹀复閸忋儰瀵岄柧淇扁偓?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Webhook 閹存牗澧滈崝銊ㄐ曢崣?2. Normalize Manual Media Request
3. 4_video_transcript_ingest
4. 5_common_vault_writer
5. 3b_qdrant_commit
6. Respond to Webhook

鏉堝湱鏅痪锔芥将閿?
- 鏉╂瑤閲滈崗銉ュ經閸欘亝甯?media URL閿涘奔绗夐幒銉︽瀮缁旂姵顒滈弬鍥モ偓浣稿閽樺繑鏋冮張顒佸灗闁氨鏁ら幍瀣З缁楁棁顔囬妴?- URL 鏉╂稑鍙嗛崥搴″帥鐠?4_video_transcript_ingest閿涘奔绗夌憰渚€鍣搁弬鏉垮絺閺勫簼绔存總妤勬祮瑜版洘鍨ㄩ幗妯款洣闁槒绶妴?- 4_video_transcript_ingest 閸欘亣绻戦崶鐐板瘜缁捐法绮ㄩ弸婊愮礉娑撳秴婀崘鍛村劥閻╁瓨甯撮崘?Vault閿涙稑鍟撴惔鎾剁埠娑撯偓鐠ф澘鍙℃禍?5_common_vault_writer閿涘瞼鍌ㄥ鏇犵埠娑撯偓鐠?3b_qdrant_commit閵?- source_type 鎼存柧绻氶悾娆忓敶鐎硅娼靛┃鎰嚔娑斿绱濇笟瀣洤 podcast 閹?	ranscript閿涘奔绗夌憰浣告礈娑撳搫鐣犻弰顖涘閸斻劏袝閸欐垵姘ㄩ弫缈犵秼閺€瑙勫灇 manual閵?- 閸欘垯浜掓潻钘夊 manual-submit tag閿涘瞼鏁ら弶銉︾垼鐠囧棜袝閸欐垶鏌熷蹇ョ幢娑撳秷顩︾拋鈺佺暊濮光剝鐓嬮崢濠氬櫢閵嗕胶绮虹拋鈥虫嫲閺夈儲绨拠顓濈疅閵?- 姒涙顓婚張顒€婀?webhook 鐠侯垰绶炴担璺ㄦ暏 POST /webhook/aip/local/manual-media-submit閵?- 閸︺劌缍嬮崜?repo JSON 閻╂潙鎮撳銉ュ煂 SQLite 閻ㄥ嫯绻嶇悰灞灸佸蹇庣瑓閿涘ive webhook 鐎圭偤妾▔銊ュ斀鐠侯垰绶炴禒?webhook_entity.webhookPath 娑撳搫鍣敍灞界箑鐟曚焦妞傞崗鍫滅矤 deploy/data/n8n/database.sqlite 閺屻儴顕楅崥搴″晙鐠嬪啰鏁ら妴?### 7_memos_branch_ingest

閼卞矁鐭楅敍姘暜鐠侯垰顤冨鐚寸礉娑撳秵濮犳稉璇插叡鐟欐帟澹婇妴?
瀵ら缚顔呴懞鍌滃仯妞ゅ搫绨敍?
1. Webhook 閹?Memos 娴滃娆?2. 0_common_normalize_text_object
3. 1a_rule_prefilter
4. 3_qdrant_gate
5. IF should_continue_to_llm
6. 2_enrich_with_llm
7. 4a_action_policy
8. 5_common_vault_writer
9. 3b_qdrant_commit
## Qdrant 闂嗗棗鎮庨崚婵嗩潗閸?

閸?n8n 闁插苯鍘涢幍褑顢戞稉鈧▎鈽呯窗

```http
PUT http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}
Content-Type: application/json

{
  "vectors": {
    "size": {{$env.QDRANT_VECTOR_SIZE}},
    "distance": "Cosine"
  }
}
```

## Qdrant 閹兼粎鍌ㄧ拠閿嬬湴閺嶈渹绶?

```http
POST http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}/points/search
Content-Type: application/json

{
  "vector": {{$json.embedding}},
  "limit": 1,
  "with_payload": true
}
```

## Qdrant Upsert 閺嶈渹绶?

```http
PUT http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}/points
Content-Type: application/json

{
  "points": [
    {
      "id": "{{$json.qdrant_point_id}}",
      "vector": {{$json.embedding}},
      "payload": {
        "item_id": "{{$json.item_id}}",
        "title": "{{$json.title}}",
        "canonical_url": "{{$json.canonical_url}}",
        "published_at": "{{$json.published_at}}",
        "dedupe_action": "{{$json.dedupe_action}}"
      }
    }
  ]
}
```

## 娑撳楠囬梽宥呮珨娴狅絿鐖滈懞鍌滃仯

```javascript
const match = $json.qdrant_result?.[0];

if (!match || match.score < 0.85) {
  return [{ json: { ...$json, action: 'full_push' } }];
}

if (match.score < 0.97) {
  return [{ json: { ...$json, action: 'diff_push', matched_payload: match.payload } }];
}

return [{ json: { ...$json, action: 'silent', matched_payload: match.payload } }];
```

## 閹绘劗銇氱拠宥囧鐎?

- `LLM_MODEL` 鐠愮喕鐭楅幍鎾冲瀻閵嗕焦鎲崇憰浣碘偓浣圭垼缁涙儳鎷扮拠鍕啈
- `EMBEDDING_MODEL` 閸欘亣绀嬬拹锝囨晸閹存劕鎮滈柌?
- 娑撳秷顩﹂幎濠冨ⅵ閸掑棙膩閸ㄥ鎷?embedding 濡€崇€峰ǎ閿嬪灇娑撯偓娑擃亪鍘ょ純顕€銆?
- 閼汇儱鍨忛幑?embedding 濡€崇€烽敍灞界箑妞よ鎮撳銉︻梾閺?collection 缂佹潙瀹抽弰顖氭儊閸栧綊鍘?

## Obsidian 閺傚洣娆㈢痪锕€鐣?

- 娑撹绨辩捄顖氱窞閿涙瓪/vault`
- 閺€鏈垫缁犺京娲拌ぐ鏇窗`/vault/{{$env.OBSIDIAN_INBOX_DIR}}`
- Daily Notes 閻╊喖缍嶉敍姝?vault/{{$env.OBSIDIAN_DAILY_DIR}}`

瀵ら缚顔呴弬鍥︽閸氬稄绱?

`{date}_{source_type}_{item_id[:10]}_{slug}.md`

瀵ら缚顔?frontmatter閿?

```yaml
---
title: 閺嶅洭顣?
item_id: 6d6e2f96ab2c
source_type: rss
source_name: 閺夈儲绨崥宥囆?
canonical_url: 閸樼喐鏋冮柧鐐复
published_at: 2026-04-17T09:00:00-04:00
ingested_at: 2026-04-17T09:05:00-04:00
content_hash: sha256:...
score: 0
category: pending
tags:
  - inbox
  - ai-information-processor
dedupe_action: full_push
status: raw
---
```
## 鏉╂劘顢戦幀浣告倱濮?

- 娴犳挸绨遍崘鍛畱 `deploy/n8n/workflows/*.json` 閹靛秵妲稿銉ょ稊濞翠礁鐣炬稊澶屾畱 source of truth
- 娑撳秷顩︾紒褏鐢婚幍瀣暭 `deploy/data/n8n/database.sqlite`
- 鐎电懓顦婚崣顏冨▏閻?`python deploy/n8n/scripts/publish_runtime.py` 娴ｆ粈璐熼崣鎴濈閸忋儱褰?
- `publish_runtime.py` 閸愬懘鍎存导姘崇殶閻?`sync_workflows.py`閿涘苯鑻熼幎濠傜暊閸ュ搫鐣炬稉鍝勬暜娑撯偓 SQLite 閸愭瑥鍙嗗銉╊€?
- 閸欐垵绔烽柧鎹愮熅閸ュ搫鐣炬稉?`sync -> restart n8n -> check_runtime_alignment`
- 閺嶅湱娲拌ぐ?`DEBUG_LOG.md` 閺勵垳绮烘稉鈧拫鍐槸閺冦儱绻旈敍灞藉絺鐢?閸氬本顒?閺嶏繝鐛欓懘姘拱闁垝绱版潻钘夊閸掓媽绻栭柌?
- 娴ｈ法鏁?`python deploy/n8n/scripts/smoke_qdrant_gate.py` 閸︺劎绮撶粩顖欐櫠濡偓閺?embedding 闁板秶鐤嗛妴涔llection 缂佹潙瀹抽崪灞肩瑏缁?`dedupe_action` 閻ㄥ嫬鐤勯梽鍛瀻閺€顖滅波閺?
- 娴犳挸绨遍弽鍦窗瑜?`.pre-commit-config.yaml` 瀹稿弶甯撮崗?`contracts/validate_contract.py` 閸?`smoke_qdrant_gate.py`閿涙稐鎱ㄩ弨?workflow/runtime 閻╃鍙ч弬鍥︽閺冭绱濋幓鎰唉閸撳秳绱伴崗鍫ｇ獓閺堫剙婀寸€瑰牓妫?
- `sync_workflows.py` 娴兼艾鍘涙径鍥﹀敜濞茶濮?SQLite 鎼存搫绱濋崘宥埶夋?`workflow_entity` 閸?`workflow_history`
- 鐞?`Execute Workflow` 鐠嬪啰鏁ら惃鍕摍瀹搞儰缍斿ù渚婄礉韫囧懘銆忛崥灞炬閸忓嘲顦敍?
  - `workflow_entity.active = true`
  - `workflow_entity.activeVersionId = versionId`
  - `workflow_history.versionId = versionId`
- 瑜版挸澧?`02_enrich_with_llm` 閸?`03_qdrant_gate` 闁垝绶风挧鏍箹娑撳銆嶉敍宀€宸辨禒缁樺壈娑撯偓妞ゅ綊鍏樻导姘躬鏉╂劘顢戦弮鎯靶曢崣?`Workflow is not active`
## Transcript Runtime Boundary

閸︺劍甯撻弻?`04_video_transcript_ingest` 閸撳稄绱濋崗鍫濇祼鐎规俺绻栨稉銈勯嚋娴滃鐤勯敍?

- `CapsWriter` 閺勵垰顔栨稉缁樻簚閺堫剙婀撮張宥呭閿涘奔绗夐崷?Docker 闁插矉绱辫ぐ鎾冲閸︽澘娼冮弰?`ws://host.docker.internal:6016`
- `FunASR` 閺?Docker 閸愬懏婀囬崝鈽呯幢瑜版挸澧犻崷鏉挎絻閺?`ws://funasr-spk-server:8767`

閸忓牆灏崚鍡楊問娑撶粯婧€閺堫剙婀撮張宥呭閸?Docker 閸愬懏婀囬崝鈽呯礉閸愬秶鎴风紒顓犳箙 workflow 閼哄倻鍋ｉ張顒冮煩閵嗗倽顕涚紒鍡氼嚛閺勫氦顫?`deploy/TRANSCRIPT_RUNTIME_INVARIANTS.md`閵?
