import {describe,it,expect} from 'vitest';import{formatMetric,isImprovement}from'./metrics';
describe('metric helpers',()=>{it('formats missing values transparently',()=>expect(formatMetric(null)).toBe('—'));it('detects lower cycle time as improvement',()=>expect(isImprovement(10,8)).toBe(true));});
