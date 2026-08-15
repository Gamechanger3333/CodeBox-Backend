const { validationResult } = require('express-validator');
const prisma = require('../models/prismaClient');
const {
  generateInterviewQuestions,
  evaluateAnswer,
  generateFinalReport,
} = require('../utils/interviewAnalyzer');

const MAX_ANSWER_LENGTH = 4000; // same reasoning as other LLM-facing inputs — cap cost per request

const validate = (req, res) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    res.status(400).json({ error: errors.array()[0].msg });
    return false;
  }
  return true;
};

// ─────────────────────────────────────────────────────────────────────────────
// Start (or resume) an interview for the currently loaded project.
// If an InterviewSession already exists for this project, return it as-is
// rather than regenerating questions (regenerating would invalidate any
// progress already made and cost an extra AI call for nothing).
// ─────────────────────────────────────────────────────────────────────────────
exports.startInterview = async (req, res, next) => {
  try {
    const userId = req.user.id;

    const projectSession = await prisma.projectSession.findUnique({ where: { userId } });
    if (!projectSession) {
      return res.status(404).json({ error: 'No project loaded. Please upload a project first.' });
    }

    const existing = await prisma.interviewSession.findUnique({ where: { userId } });
    if (existing && existing.projectSessionId === projectSession.id) {
      return res.json(formatSessionResponse(existing));
    }

    // Either no interview yet, or the project was replaced since the last
    // interview — generate a fresh question set for the current project.
    const files = JSON.parse(projectSession.files);
    const questions = await generateInterviewQuestions(projectSession.fileTree, files);

    const data = {
      userId,
      projectSessionId: projectSession.id,
      questions: JSON.stringify(questions),
      transcript: '[]',
      currentIndex: 0,
      status: 'in_progress',
      report: null,
    };

    const session = await prisma.interviewSession.upsert({
      where: { userId },
      update: data,
      create: data,
    });

    res.json(formatSessionResponse(session));
  } catch (error) {
    console.error('Start interview error:', error);
    next(error);
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Submit an answer to the current question, get feedback + the next question.
// ─────────────────────────────────────────────────────────────────────────────
exports.submitAnswer = async (req, res, next) => {
  try {
    if (!validate(req, res)) return;

    const userId = req.user.id;
    const { answer } = req.body;

    if (!answer?.trim()) {
      return res.status(400).json({ error: 'No answer provided' });
    }
    if (answer.length > MAX_ANSWER_LENGTH) {
      return res.status(400).json({ error: `Answer too long (max ${MAX_ANSWER_LENGTH} characters)` });
    }

    const session = await prisma.interviewSession.findUnique({ where: { userId } });
    if (!session) {
      return res.status(404).json({ error: 'No interview in progress. Start one first.' });
    }
    if (session.status === 'completed') {
      return res.status(400).json({ error: 'This interview is already complete.' });
    }

    const questions = JSON.parse(session.questions);
    const currentQuestion = questions[session.currentIndex];
    if (!currentQuestion) {
      return res.status(400).json({ error: 'No more questions in this interview.' });
    }

    const projectSession = await prisma.projectSession.findUnique({ where: { id: session.projectSessionId } });
    if (!projectSession) {
      return res.status(404).json({ error: 'The project this interview was based on no longer exists.' });
    }
    const files = JSON.parse(projectSession.files);
    const transcript = JSON.parse(session.transcript);

    const evaluation = await evaluateAnswer(
      projectSession.fileTree,
      files,
      currentQuestion.question,
      answer,
      transcript
    );

    const updatedTranscript = [
      ...transcript,
      {
        questionId: currentQuestion.id,
        category: currentQuestion.category,
        question: currentQuestion.question,
        answer,
        feedback: evaluation.feedback,
        teach: evaluation.teach,
        followUp: evaluation.followUp,
      },
    ];

    const nextIndex = session.currentIndex + 1;
    const isLastQuestion = nextIndex >= questions.length;

    const updated = await prisma.interviewSession.update({
      where: { userId },
      data: {
        transcript: JSON.stringify(updatedTranscript),
        currentIndex: nextIndex,
        status: isLastQuestion ? 'ready_for_report' : 'in_progress',
      },
    });

    res.json({
      feedback: evaluation.feedback,
      teach: evaluation.teach,
      followUp: evaluation.followUp,
      isLastQuestion,
      nextQuestion: isLastQuestion ? null : questions[nextIndex],
      progress: { current: nextIndex, total: questions.length },
      status: updated.status,
    });
  } catch (error) {
    console.error('Submit answer error:', error);
    next(error);
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Generate the final report (separate step from the last answer, since
// report generation is a slower/heavier AI call — let the frontend show
// the last question's feedback immediately, then request the report).
// ─────────────────────────────────────────────────────────────────────────────
exports.finishInterview = async (req, res, next) => {
  try {
    const userId = req.user.id;

    const session = await prisma.interviewSession.findUnique({ where: { userId } });
    if (!session) {
      return res.status(404).json({ error: 'No interview found.' });
    }
    if (session.status === 'completed' && session.report) {
      return res.json({ report: session.report });
    }

    const projectSession = await prisma.projectSession.findUnique({ where: { id: session.projectSessionId } });
    if (!projectSession) {
      return res.status(404).json({ error: 'The project this interview was based on no longer exists.' });
    }
    const files = JSON.parse(projectSession.files);
    const transcript = JSON.parse(session.transcript);

    if (transcript.length === 0) {
      return res.status(400).json({ error: 'Answer at least one question before requesting a report.' });
    }

    const report = await generateFinalReport(projectSession.fileTree, files, transcript);

    await prisma.interviewSession.update({
      where: { userId },
      data: { status: 'completed', report },
    });

    res.json({ report });
  } catch (error) {
    console.error('Finish interview error:', error);
    next(error);
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Get current interview state (called on page load to restore progress)
// ─────────────────────────────────────────────────────────────────────────────
exports.getInterviewSession = async (req, res) => {
  try {
    const userId = req.user.id;
    const session = await prisma.interviewSession.findUnique({ where: { userId } });

    if (!session) {
      return res.json({ hasInterview: false });
    }

    res.json({ hasInterview: true, ...formatSessionResponse(session) });
  } catch (error) {
    console.error('Get interview session error:', error);
    res.json({ hasInterview: false });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// Reset — delete the interview session so a new one can be started for the
// same project (e.g. user wants to retry from scratch).
// ─────────────────────────────────────────────────────────────────────────────
exports.resetInterview = async (req, res) => {
  try {
    const userId = req.user.id;
    await prisma.interviewSession.deleteMany({ where: { userId } });
    res.json({ success: true });
  } catch (error) {
    console.error('Reset interview error:', error);
    res.json({ success: true });
  }
};

function formatSessionResponse(session) {
  const questions = JSON.parse(session.questions);
  const transcript = JSON.parse(session.transcript);
  return {
    status: session.status,
    progress: { current: session.currentIndex, total: questions.length },
    currentQuestion: questions[session.currentIndex] || null,
    transcript,
    report: session.report || null,
  };
}
