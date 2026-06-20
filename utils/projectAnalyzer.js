/**
 * utils/projectAnalyzer.js
 *
 * Re-exports from controllers/Projectanalyzer.js so that
 * controllers/projectController.js can require('../utils/projectAnalyzer')
 * without a case-sensitive path error on Linux/Mac.
 *
 * Place this file at:  CodeBox-Backend/utils/projectAnalyzer.js
 */
const {
  extractProjectFiles,
  analyzeProject,
  askAboutProject,
  buildFileTree,
  buildProjectContext,
} = require('../controllers/Projectanalyzer');

module.exports = {
  extractProjectFiles,
  analyzeProject,
  askAboutProject,
  buildFileTree,
  buildProjectContext,
};