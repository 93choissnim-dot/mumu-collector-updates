from vision import LABELS
EXTRA_LABELS={'ranking':'랭킹 수령','worldboss':'월드보스 보상','excavation':'유물 발굴','training':'수련'}
DAILY_LABELS={'daily_pass':'패스 수령','daily_dungeons':'1일 던전','daily_guild':'길드'}
TASK_LABELS={**LABELS,**EXTRA_LABELS,**DAILY_LABELS}
PAGE_MARKERS={
 'boss_rank':('x_boss_rank_title','x_boss_rank_tab'),
 'boss_select':('x_boss_select_title','x_boss_card','x_boss_card_kraken','x_boss_card_void'),
 'training':('x_train_title','x_train_tab'),
 'ranking':('x_rank_title','x_rank_tab'),
 'excavation':('x_dig_title','x_dig_resource'),
 'relic':('x_relic_title','x_relic_tab'),
 'boss':('x_boss_mission','x_boss_rank_open','x_boss_power','x_boss_supply'),
}
