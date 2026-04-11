-- 为馆藏书目表补全字段注释（请将 `library_book` 改为你的实际表名后执行）
-- MySQL 5.7+ / 8.0+

ALTER TABLE library_book
  MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键：自增记录编号，与业务无关，仅用于表内行关联',
  MODIFY COLUMN book_key VARCHAR(64) NOT NULL COMMENT '书籍业务标识：条码/馆藏记录号等，全表唯一，用于借还与查询',
  MODIFY COLUMN lib_book VARCHAR(255) NOT NULL COMMENT '书籍正题名：展示与检索用，可与索书号、book_key 联合定位',
  MODIFY COLUMN book_pos VARCHAR(255) NULL COMMENT '馆藏位置：架位/库区/层架说明，可空表示暂未编目或未上架',
  MODIFY COLUMN is_borrow TINYINT(1) NOT NULL DEFAULT 0 COMMENT '在馆状态：0=在馆可借，1=已借出（若有借阅流水表可与之同步）',
  MODIFY COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间：首次写入本行数据的时间',
  MODIFY COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间：书目信息或借阅状态最后一次变更时间';

-- 表级注释（可选）
ALTER TABLE library_book COMMENT = '馆藏书目主数据：标识、题名、架位与在馆状态，供 OPAC/对话助手查询';

-- 若主键为 BIGINT UNSIGNED，将 `BIGINT` 改为 `BIGINT UNSIGNED` 再执行。
