import { useSession } from '../../../../contexts/SessionContext';
import styles from './AnalyserConfig.module.css';

const AnalyserConfig = () => {
  const { session, updateAnalyser } = useSession();

  return (
    <div className={styles.analyserConfig}>
      <h2>Analyser Selection</h2>
      <ul className={styles.analyserList}>
        <li>
          <label>
            <input
              type="checkbox"
              checked={session.analysers.genre}
              onChange={(e) => updateAnalyser("genre", e.target.checked)}
            />
            Genre Analyser
          </label>
        </li>
        <li>
          <label>
            <input
              type="checkbox"
              checked={session.analysers.lyrics}
              onChange={(e) => updateAnalyser("lyrics", e.target.checked)}
            />
            Lyrics Analyser
          </label>
        </li>
      </ul>
    </div>
  );
};

export default AnalyserConfig;