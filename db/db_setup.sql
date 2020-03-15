-- --------------------------------------------------------
-- Сервер:                       lifetime.hutei.net
-- Версія сервера:               5.7.29 - MySQL Community Server (GPL)
-- ОС сервера:                   Linux
-- HeidiSQL Версія:              10.3.0.5771
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!50503 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;


-- Dumping database structure for lifetime
CREATE DATABASE IF NOT EXISTS `lifetime` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci */;
USE `lifetime`;

-- Dumping structure for таблиця lifetime.countries
CREATE TABLE IF NOT EXISTS `countries` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `overall` float NOT NULL,
  `female` float NOT NULL,
  `male` float NOT NULL,
  PRIMARY KEY (`id`),
  KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=181 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Дані для експорту не вибрані

-- Dumping structure for таблиця lifetime.languages
CREATE TABLE IF NOT EXISTS `languages` (
  `code` varchar(3) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `default` enum('Y','N') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'N',
  PRIMARY KEY (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Дані для експорту не вибрані

-- Dumping structure for таблиця lifetime.log
CREATE TABLE IF NOT EXISTS `log` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `ip` varchar(15) COLLATE utf8mb4_unicode_ci NOT NULL,
  `url` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `method` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL,
  `date` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ip` (`ip`)
) ENGINE=InnoDB AUTO_INCREMENT=143 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Дані для експорту не вибрані

-- Dumping structure for таблиця lifetime.regions
CREATE TABLE IF NOT EXISTS `regions` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `overall` float unsigned NOT NULL,
  `female` float unsigned NOT NULL,
  `male` float unsigned NOT NULL,
  PRIMARY KEY (`id`),
  KEY `name` (`name`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Дані для експорту не вибрані

-- Dumping structure for таблиця lifetime.translations
CREATE TABLE IF NOT EXISTS `translations` (
  `code` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `lang` varchar(3) COLLATE utf8mb4_unicode_ci NOT NULL,
  `translate` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`code`,`lang`),
  KEY `FK_translations_languages` (`lang`),
  CONSTRAINT `FK_translations_languages` FOREIGN KEY (`lang`) REFERENCES `languages` (`code`) ON DELETE NO ACTION ON UPDATE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Дані для експорту не вибрані

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
